#!/bin/sh
# ============================================================
#  set_sleep.sh  —  设置并固化外挂硬盘的空闲休眠时间
#
#  用法（在 NAS 上以 root 运行）：
#    sh set_sleep.sh              # 默认 120 分钟（2 小时）
#    sh set_sleep.sh 30           # 30 分钟
#    sh set_sleep.sh 240          # 4 小时
#    sh set_sleep.sh 0            # 关闭自动休眠（一直转）
#    sh set_sleep.sh 120 show     # 只显示当前配置，不改动
#
#  原理：
#    1. 用 hdparm -S 把空闲计时器写进硬盘
#    2. 用 /etc/rc.local 固化（多数盘掉电会丢这个设置）
#    3. 按型号匹配设备，避免插拔后 sdc 变成 sdd 就失效
# ============================================================

set -u
MIN="${1:-120}"
MODE="${2:-apply}"

LINE="------------------------------------------------------------"
ok()   { echo "  [OK]    $*"; }
warn() { echo "  [注意]  $*"; }
bad()  { echo "  [不可]  $*"; }
info() { echo "  [信息]  $*"; }

if [ "$(id -u)" != "0" ]; then
    echo "请用 root 运行：sudo sh $0 $*"
    exit 1
fi

# ---------- 分钟 → hdparm -S 编码 ----------
# 0        = 关闭
# 1..240   = 5 秒的倍数（5 秒 ~ 20 分钟）
# 241..251 = 30 分钟的倍数（30 分钟 ~ 5.5 小时）
encode_S() {
    m="$1"
    if [ "$m" -le 0 ]; then echo 0; return; fi
    if [ "$m" -le 20 ]; then
        echo $((m * 12))
    elif [ "$m" -ge 330 ]; then
        echo 251
    else
        echo $((240 + m / 30))
    fi
}

# ---------- 找目标盘 ----------
# 优先按型号匹配 WD Elements；找不到就退回第一个非系统 ext4 盘
find_disks() {
    found=""
    for d in /sys/block/sd*; do
        [ -e "$d" ] || continue
        dev=$(basename "$d")
        model=$(cat "$d/device/model" 2>/dev/null | sed 's/ *$//')
        case "$model" in
            *lements*|*LEMENTS*) found="$found $dev" ;;
        esac
    done
    if [ -z "$found" ]; then
        for d in /sys/block/sd*; do
            [ -e "$d" ] || continue
            dev=$(basename "$d")
            # 系统盘（含 /overlay 或 /boot）跳过
            if grep -qE "^/dev/$dev[0-9]* (/overlay|/boot|/)" /proc/mounts 2>/dev/null; then
                continue
            fi
            found="$found $dev"
        done
    fi
    echo "$found"
}

DEVS=$(find_disks | tr -s ' ')

echo "============================================================"
echo " 硬盘空闲休眠设置"
echo "============================================================"
echo ""

if [ -z "$DEVS" ]; then
    bad "没找到可用的数据盘"
    echo "  请确认硬盘已插好：block info"
    exit 1
fi

info "目标磁盘:$DEVS"
for dev in $DEVS; do
    model=$(cat "/sys/block/$dev/device/model" 2>/dev/null | sed 's/ *$//')
    size=$(awk -v s="$(cat /sys/block/$dev/size 2>/dev/null || echo 0)" 'BEGIN{printf "%.1f TB", s*512/1024/1024/1024/1000}')
    info "  /dev/$dev  $model  $size"
done

if ! command -v hdparm >/dev/null 2>&1; then
    bad "没装 hdparm，先执行：opkg update && opkg install hdparm"
    exit 1
fi

S=$(encode_S "$MIN")
echo ""
info "目标空闲时间: ${MIN} 分钟  →  hdparm -S $S"
if [ "$MIN" -gt 330 ]; then
    warn "超过 5.5 小时（硬件上限 251），已按 5.5 小时处理"
fi

if [ "$MODE" = "show" ]; then
    echo ""
    info "只显示模式，未做任何修改"
    for dev in $DEVS; do
        st=$(hdparm -C "/dev/$dev" 2>/dev/null | sed -n 's/.*drive state is: *//p')
        info "  /dev/$dev 当前状态: ${st:-读不到}"
    done
    echo ""
    echo "  rc.local 里现有的固化配置："
    grep -n "SETSLEEP" /etc/rc.local 2>/dev/null | sed 's/^/    /' || echo "    （无）"
    exit 0
fi

# ---------- 立即生效 ----------
echo ""
echo "============================================================"
echo " 1. 立即生效"
echo "============================================================"
APPLIED=""
for dev in $DEVS; do
    if hdparm -S "$S" "/dev/$dev" >/dev/null 2>&1; then
        ok "/dev/$dev 已设为 ${MIN} 分钟空闲休眠"
        APPLIED="$APPLIED $dev"
    else
        bad "/dev/$dev 设置失败（盒子可能不透传 ATA 命令）"
    fi
done

if [ -z "$APPLIED" ]; then
    echo ""
    bad "全部设置失败，无法固化"
    echo "  这种情况只能退回 hd-idle（但 hd-idle 只能催睡，不能调长）"
    exit 1
fi

# ---------- 固化到 rc.local ----------
echo ""
echo "============================================================"
echo " 2. 固化到 /etc/rc.local（防止重启丢失）"
echo "============================================================"

if [ ! -f /etc/rc.local ]; then
    warn "/etc/rc.local 不存在，创建一个"
    printf '#!/bin/sh\n\nexit 0\n' > /etc/rc.local
    chmod +x /etc/rc.local
fi

BK="/etc/rc.local.bak.$(date +%Y%m%d-%H%M%S)"
cp /etc/rc.local "$BK" 2>/dev/null && info "已备份原文件 → $BK"

BLK="/tmp/.sleepblk.$$"
{
    echo "# SETSLEEP-BEGIN 由 set_sleep.sh 生成，勿手改"
    echo "for _d in /sys/block/sd*; do"
    echo "    grep -qi elements \"\$_d/device/model\" 2>/dev/null || continue"
    echo "    /sbin/hdparm -S $S \"/dev/\${_d##*/}\" 2>/dev/null"
    echo "done"
    echo "# SETSLEEP-END"
} > "$BLK"

TMP="/tmp/.rclocal.$$"
awk -v blkfile="$BLK" '
    /# SETSLEEP-BEGIN/ { skip=1 }
    /# SETSLEEP-END/   { skip=0; next }
    skip { next }
    /^[[:space:]]*exit 0/ && !done {
        while ((getline line < blkfile) > 0) print line
        close(blkfile)
        done=1
    }
    { print }
    END {
        if (!done) {
            while ((getline line < blkfile) > 0) print line
            close(blkfile)
        }
    }
' /etc/rc.local > "$TMP"

if [ -s "$TMP" ]; then
    cat "$TMP" > /etc/rc.local
    rm -f "$TMP" "$BLK"
    ok "已写入 /etc/rc.local"
else
    bad "写入失败，原文件未改动"
    rm -f "$TMP" "$BLK"
    exit 1
fi

[ -x /etc/rc.local ] || chmod +x /etc/rc.local

echo ""
echo "  当前 rc.local 内容："
echo "$LINE"
sed 's/^/    /' /etc/rc.local
echo "$LINE"

# ---------- 校验 ----------
echo ""
echo "============================================================"
echo " 3. 校验"
echo "============================================================"
for dev in $DEVS; do
    st=$(hdparm -C "/dev/$dev" 2>/dev/null | sed -n 's/.*drive state is: *//p')
    info "/dev/$dev 当前电源状态: ${st:-读不到}"
done
echo ""
ok "完成。设置已生效，重启后由 rc.local 自动重新套用。"
echo ""
echo "  想改时间: sh set_sleep.sh 240   （4 小时）"
echo "  想看清楚: sh set_sleep.sh 120 show"
echo "  想每次启动都验证一遍: 看 /tmp/hdd_sleep_diag.sh 的输出"
