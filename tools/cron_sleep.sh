#!/bin/sh
# ============================================================
#  cron_sleep.sh  —  用 cron + hdparm -y 实现空闲休眠
#
#  为什么不用 hd-idle：
#    这块盘的 USB 桥接只认 SCSI START_STOP（即 hdparm -y），
#    不认 ATA IDLE 计时器（hdparm -S 假成功）。
#    hd-idle 1.05 在这台机器上参数正确、进程在跑，但 150 秒内
#    没有触发 spindown，无法信任。所以改用「自己计时 + 直接调 -y」，
#    完全不依赖它的黑盒判断。
#
#  特点：
#    · 每次检查都按型号重新找盘 → 设备名 sdb/sdc 变化自动适应
#    · 状态存在 /tmp，重启清零（重启后本来就是新周期，合理）
#    · 幂等：重复运行不会重复加 cron 行
#
#  用法：
#    sh cron_sleep.sh          # 默认 120 分钟，检查间隔 5 分钟
#    sh cron_sleep.sh 240      # 240 分钟
#    sh cron_sleep.sh 0        # 卸载本方案
# ============================================================

set -u
IDLE_MIN="${1:-120}"
CHECK_MIN=5

ok()   { echo "  [OK]    $*"; }
warn() { echo "  [注意]  $*"; }
bad()  { echo "  [不可]  $*"; }
info() { echo "  [信息]  $*"; }

MON="/usr/bin/disk-sleep-check.sh"
STATE="/tmp/.disksleep.state"
CRON_LINE="*/$CHECK_MIN * * * * $MON"

if [ "$(id -u)" != "0" ]; then
    echo "请用 root 运行：sudo sh $0 $*"
    exit 1
fi

# ---------- 卸载 ----------
if [ "$IDLE_MIN" = "0" ]; then
    echo "============================================================"
    echo " 卸载本方案"
    echo "============================================================"
    sed -i "\|$MON|d" /etc/crontabs/root 2>/dev/null
    /etc/init.d/cron restart >/dev/null 2>&1
    rm -f "$MON" "$STATE"
    ok "已移除 cron 行、监控脚本和状态文件"
    echo ""
    warn "注意：hd-idle 仍在运行且已设为开机自启"
    echo "  要一并关掉：/etc/init.d/hd-idle disable && /etc/init.d/hd-idle stop"
    exit 0
fi

# ---------- 找盘 ----------
find_dev() {
    for d in /sys/block/sd*; do
        [ -e "$d" ] || continue
        if grep -qi elements "$d/device/model" 2>/dev/null; then
            basename "$d"
            return 0
        fi
    done
    return 1
}

DEV=$(find_dev) || { bad "没找到 Elements 盘"; exit 1; }

getstate() {
    hdparm -C "/dev/$1" 2>/dev/null | sed -n 's/.*drive state is: *//p'
}

echo "============================================================"
echo " 用 cron + hdparm -y 实现空闲休眠"
echo "============================================================"
echo ""
info "目标磁盘: /dev/$DEV"
info "型号: $(cat "/sys/block/$DEV/device/model" 2>/dev/null | sed 's/ *$//')"
info "空闲阈值: ${IDLE_MIN} 分钟"
info "检查间隔: ${CHECK_MIN} 分钟"
echo ""

if ! command -v hdparm >/dev/null 2>&1; then
    bad "没装 hdparm：opkg update && opkg install hdparm"
    exit 1
fi

# ---------- 1. 确认 hdparm -y 现在仍然有效 ----------
echo "------------------------------------------------------------"
echo " 1. 确认 hdparm -y 现在还能让盘立刻睡"
echo "------------------------------------------------------------"
if ! hdparm -y "/dev/$DEV" >/dev/null 2>&1; then
    bad "hdparm -y 失败 —— 连立即停转都不支持，本方案不适用"
    exit 1
fi
sleep 4
st=$(getstate "$DEV")
case "$st" in
    standby|sleep)
        ok "已进入 $st —— START_STOP 通路有效，方案可行"
        ;;
    *)
        warn "状态显示 $st（部分盒子不上报，继续往下做）"
        ;;
esac

# ---------- 2. 装监控脚本 ----------
echo ""
echo "------------------------------------------------------------"
echo " 2. 安装监控脚本 $MON"
echo "------------------------------------------------------------"

cat > "$MON" <<'EOS'
#!/bin/sh
# 由 cron_sleep.sh 生成：空闲足够久就发 START_STOP 让盘停转。
# 每次运行都按型号重新找盘，设备名变了也不受影响。
IDLE_MIN=__IDLE_MIN__
SF=/tmp/.disksleep.state

DEV=""
for d in /sys/block/sd*; do
    [ -e "$d" ] || continue
    if grep -qi elements "$d/device/model" 2>/dev/null; then
        DEV=$(basename "$d")
        break
    fi
done
[ -z "$DEV" ] && exit 0

cur=$(awk -v d="$DEV" '$3==d {print $4+$8}' /proc/diskstats 2>/dev/null)
[ -z "$cur" ] && exit 0
now=$(date +%s)

if [ ! -f "$SF" ]; then
    echo "$cur $now" > "$SF"
    exit 0
fi

last_io=$(awk '{print $1}' "$SF" 2>/dev/null)
last_ts=$(awk '{print $2}' "$SF" 2>/dev/null)
[ -z "$last_io" ] && last_io=0
[ -z "$last_ts" ] && last_ts=$now

if [ "$cur" != "$last_io" ]; then
    # 有新的读写，重新计时
    echo "$cur $now" > "$SF"
    exit 0
fi

idle=$(( (now - last_ts) / 60 ))
[ "$idle" -lt "$IDLE_MIN" ] && exit 0

st=$(hdparm -C "/dev/$DEV" 2>/dev/null | sed -n 's/.*drive state is: *//p')
case "$st" in
    standby|sleep)
        exit 0
        ;;
esac

if hdparm -y "/dev/$DEV" >/dev/null 2>&1; then
    logger -t disksleep "spindown $DEV after ${idle}min idle"
fi
exit 0
EOS

sed -i "s|__IDLE_MIN__|$IDLE_MIN|" "$MON"
chmod +x "$MON"
ok "已写入并赋予执行权限"

# 初始化状态
cur=$(awk -v d="$DEV" '$3==d {print $4+$8}' /proc/diskstats 2>/dev/null)
echo "${cur:-0} $(date +%s)" > "$STATE"
ok "状态文件已初始化: $STATE"

# ---------- 3. 装 cron ----------
echo ""
echo "------------------------------------------------------------"
echo " 3. 注册定时任务（每 ${CHECK_MIN} 分钟）"
echo "------------------------------------------------------------"

mkdir -p /etc/crontabs
touch /etc/crontabs/root
# 幂等：先删旧行再加
sed -i "\|$MON|d" /etc/crontabs/root 2>/dev/null
echo "$CRON_LINE" >> /etc/crontabs/root
ok "cron 行已写入 /etc/crontabs/root"

# crond 不一定在跑
if ! pidof crond >/dev/null 2>&1; then
    /etc/init.d/cron enable >/dev/null 2>&1
    /etc/init.d/cron start >/dev/null 2>&1
    sleep 1
fi
if pidof crond >/dev/null 2>&1; then
    ok "crond 正在运行"
    /etc/init.d/cron enable >/dev/null 2>&1
else
    warn "crond 起不来，检查 /etc/init.d/cron"
fi

# ---------- 4. 逻辑自测（不等真实时间）----------
echo ""
echo "------------------------------------------------------------"
echo " 4. 自测：伪造「已空闲很久」的状态，看会不会触发"
echo "------------------------------------------------------------"
now=$(date +%s)
fake_ts=$(( now - (IDLE_MIN + 30) * 60 ))
echo "$cur $fake_ts" > "$STATE"
info "已把状态改成「${IDLE_MIN} 分钟前有过 I/O」，手动跑一次监控脚本..."
sh "$MON"
sleep 4
st=$(getstate "$DEV")
case "$st" in
    standby|sleep)
        ok "触发成功，盘已进入 $st —— 逻辑和 -y 都正常"
        ;;
    *)
        warn "当前状态 $st（可能盒子不上报，或真的没睡）"
        echo "  手动确认：hdparm -C /dev/$DEV"
        ;;
esac

# 恢复真实状态
echo "$cur $(date +%s)" > "$STATE"

# ---------- 5. 收尾 ----------
echo ""
echo "------------------------------------------------------------"
echo " 5. 停掉无效的 hd-idle"
echo "------------------------------------------------------------"
if pidof hd-idle >/dev/null 2>&1; then
    /etc/init.d/hd-idle stop >/dev/null 2>&1
    /etc/init.d/hd-idle disable >/dev/null 2>&1
    ok "hd-idle 已停止并取消开机自启（避免两套机制互相干扰）"
else
    info "hd-idle 未在运行"
fi

echo ""
echo "============================================================"
echo " 配置完成"
echo "============================================================"
echo ""
echo "  空闲 ${IDLE_MIN} 分钟后自动停转"
echo "  每 ${CHECK_MIN} 分钟检查一次，用 /proc/diskstats 判断有没有 I/O"
echo "  每次检查都按型号找盘 → 重启后设备名变化也能自愈"
echo ""
echo "  查看日志: logread | grep disksleep"
echo "  查看配置: cat /etc/crontabs/root"
echo "  卸载    : sh $0 0"
echo ""
echo "  注意：这个方案只能"至少等 ${IDLE_MIN} 分钟"再睡，"
echo "        实际入睡时间在 ${IDLE_MIN} 到 $((IDLE_MIN + CHECK_MIN)) 分钟之间。"
echo ""
