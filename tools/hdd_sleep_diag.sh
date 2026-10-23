#!/bin/sh
# ============================================================
#  hdd_sleep_diag.sh  —  iStoreOS / OpenWrt 外挂硬盘休眠体检
#
#  回答三个问题：
#    1. 这块盘的盒子到底支不支持休眠（hdparm 透传与否）
#    2. 强制睡下去之后，多久被吵醒
#    3. 到底是哪个进程在偷偷读写
#
#  特点：不依赖 iotop / btrace / smartctl，只用 /proc，
#        busybox ash 可直接跑，纯 POSIX sh。
#
#  用法（在 NAS 上以 root 运行）：
#    sh hdd_sleep_diag.sh              # 自动检测所有 sd*
#    sh hdd_sleep_diag.sh sdc          # 只查 /dev/sdc
#    sh hdd_sleep_diag.sh sdc 120      # 采样 120 秒（默认 60）
#
#  只读体检为主。唯一会改动硬盘的两处：
#    a) 第 1 节 hdparm -S 244 —— 把待机计时器写进固件（= 2 小时），可逆，
#       想恢复原样改回别的值即可；不想要这一步就把第 1 节那段注释掉
#    b) 第 4 节 hdparm -y —— 临时催睡，60 秒内自动恢复，无害
# ============================================================

set -u
SAMPLE_SECS="${2:-60}"
DEV_ARG="${1:-}"

LINE="------------------------------------------------------------"
hdr()  { echo ""; echo "============================================================"; echo " $*"; echo "============================================================"; }
ok()   { echo "  [OK]    $*"; }
warn() { echo "  [注意]  $*"; }
bad()  { echo "  [不可]  $*"; }
info() { echo "  [信息]  $*"; }

if [ "$(id -u)" != "0" ]; then
    echo "请用 root 运行：sudo sh $0 $*"
    exit 1
fi

# ---------- 0. 找盘 ----------
hdr "0. 设备与挂载"

if [ -n "$DEV_ARG" ]; then
    DEVS="$DEV_ARG"
else
    DEVS=$(ls /sys/block 2>/dev/null | grep -E '^sd[a-z]$' | tr '\n' ' ')
fi

if [ -z "$DEVS" ]; then
    bad "没找到任何 /dev/sd* 设备，盘可能没插好或被盒子挡住了"
    exit 1
fi

for d in $DEVS; do
    model=$(cat "/sys/block/$d/device/model" 2>/dev/null | sed 's/ *$//')
    size=$(awk -v s="$(cat /sys/block/$d/size 2>/dev/null || echo 0)" 'BEGIN{printf "%.1f TB", s*512/1024/1024/1024/1000}')
    echo ""
    info "/dev/$d   型号: ${model:-未知}   容量: $size"
    # 挂载点与文件系统
    mnt=$(awk -v dev="/dev/$d" 'index($1, dev) == 1 {printf "%s(%s) ", $2, $3}' /proc/mounts 2>/dev/null)
    if [ -n "$mnt" ]; then
        info "  已挂载: $mnt"
    else
        info "  未挂载"
    fi
    # 睡眠/待机 状态
    if command -v hdparm >/dev/null 2>&1; then
        st=$(hdparm -C "/dev/$d" 2>/dev/null | sed -n 's/.*drive state is: *//p')
        info "  当前电源状态: ${st:-读不到}"
    fi
done

# ---------- 1. hdparm 能力 ----------
hdr "1. hdparm 是否可用、盒子是否透传 ATA 命令"

HAVE_HD=1
if ! command -v hdparm >/dev/null 2>&1; then
    HAVE_HD=0
    bad "没装 hdparm —— 先执行：opkg update && opkg install hdparm"
    echo ""
    echo "  没有 hdparm 就只剩 hd-idle 一条路，而 hd-idle 只能'催睡'，"
    echo "  无法把休眠时间调长。"
    echo "  本次跳过第 1 节和第 4 节，其余检测（谁在写盘、SMB 现状）照常进行。"
    echo ""
else
    ok "hdparm 已安装：$(hdparm -V 2>/dev/null | head -1)"
fi

if [ "$HAVE_HD" = 1 ]; then
for d in $DEVS; do
    echo ""
    info "测试 /dev/$d"
    # APM 读
    apm=$(hdparm -B "/dev/$d" 2>&1 | sed -n 's/.*APM_level.*= *//p')
    if [ -n "$apm" ]; then
        info "  APM level = $apm  （255/254=不省电，128=允许待机，1=最省电）"
    else
        warn "  读不到 APM level（部分 USB 盒子不透传 -B）"
    fi
    # 关键的写测试：把待机计时器写进固件
    echo -n "  尝试写入待机计时器 (hdparm -S 244 = 2 小时) ... "
    if out=$(hdparm -S 244 "/dev/$d" 2>&1); then
        echo "成功"
        ok "  这块盘的盒子支持 hdparm -S，可以走'写固件'路线"
        echo "     → 不依赖任何后台服务，插件可以不要"
        echo "     → 但多数盘掉电会丢，要用 rc.local 固化才能长期生效"
    else
        echo "失败"
        bad "  盒子不透传 ATA 命令，hdparm -S 用不了"
        echo "     $(echo "$out" | head -2 | sed 's/^/     /')"
        echo "     → 只能退回 hd-idle 路线（且只能催睡，不能调长）"
    fi
done
fi

# ---------- 2. 谁在写盘 ----------
hdr "2. 谁在读写这块盘（采样 ${SAMPLE_SECS} 秒，不依赖 iotop）"

snap_io() {
    out="$1"
    : > "$out"
    for p in /proc/[0-9]*; do
        [ -r "$p/io" ] || continue
        w=$(awk '/^write_bytes:/{print $2}' "$p/io" 2>/dev/null)
        r=$(awk '/^read_bytes:/{print $2}' "$p/io" 2>/dev/null)
        [ -n "$w" ] || continue
        n=$(tr -d '\000' < "$p/comm" 2>/dev/null | head -c 20)
        echo "${p#/proc/} ${n:-?} ${w:-0} ${r:-0}" >> "$out"
    done
}

T1="/tmp/.hdio1.$$"
T2="/tmp/.hdio2.$$"
snap_io "$T1"
echo "  采样中（${SAMPLE_SECS}s，请勿操作 NAS）..."
i=0
while [ "$i" -lt "$SAMPLE_SECS" ]; do
    sleep 1
    i=$((i+1))
    [ $((i % 15)) -eq 0 ] && echo -n "  ."
done
echo ""
snap_io "$T2"

echo ""
echo "  按'块设备写入量'排序的前 6 名："
awk -v s="$SAMPLE_SECS" '
    NR==FNR { w[$1]=$3; n[$1]=$2; next }
    { if ($1 in w) { d = $3 - w[$1]; if (d > 0) printf "%9.1f KB/s   pid=%-7s %s\n", d/1024/s, $1, $2 } }
' "$T1" "$T2" | sort -rn | head -6 | sed 's/^/    /'

# 如果上面全空，说明进程层面没写，那嫌疑在读
echo ""
echo "  按'块设备读取量'排序的前 6 名："
awk -v s="$SAMPLE_SECS" '
    NR==FNR { r[$1]=$4; n[$1]=$2; next }
    { if ($1 in r) { d = $4 - r[$1]; if (d > 0) printf "%9.1f KB/s   pid=%-7s %s\n", d/1024/s, $1, $2 } }
' "$T1" "$T2" | sort -rn | head -6 | sed 's/^/    /'
rm -f "$T1" "$T2"

# ---------- 2b. SMB 现状 ----------
hdr "2b. SMB 共享现状（SMB 在用的时候，盘本来就不该睡）"

if ps 2>/dev/null | grep -q '[s]mbd'; then
    ok "smbd 正在运行（Samba，用户态）"
elif ps 2>/dev/null | grep -q '[k]smbd'; then
    info "用的是 ksmbd（内核态 SMB），行为与 Samba 不同 — 它默认不跟踪空闲，休眠更难触发"
else
    warn "没看到 smbd / ksmbd 进程"
fi

if command -v smbstatus >/dev/null 2>&1; then
    echo ""
    echo "  当前已连接的客户端（有客户端挂着，盘就不会闲）："
    smbstatus -b 2>/dev/null | head -12 | sed 's/^/    /'
    echo ""
    echo "  当前被打开的文件："
    smbstatus -L 2>/dev/null | head -12 | sed 's/^/    /'
else
    warn "没有 smbstatus 命令，跳过会话详情（可 opkg install samba4-utils）"
fi

echo ""
echo "  smb.conf 里的关键参数："
for f in /etc/samba/smb.conf /etc/samba/smb.conf.template; do
    [ -r "$f" ] && grep -inE '^[[:space:]]*(deadtime|oplocks|level2 oplocks|aio|posix locking|strict allocate)' "$f" 2>/dev/null | sed "s|^|    [$(basename "$f")] |"
done
dt=$(grep -iE '^[[:space:]]*deadtime' /etc/samba/smb.conf 2>/dev/null | head -1 | sed 's/.*= *//')
info "deadtime = ${dt:-未显式设置（默认 15 分钟断开空闲连接）}"
echo "     想让它更快断开空闲会话 → 在 [global] 里加 deadtime = 5"

# ---------- 3. 内核层面的 I/O（含无主 I/O）----------
hdr "3. 内核侧 I/O 计数（能抓到"没有进程归主"的写入，如 ext4lazyinit）"

read_sectors() { awk -v d="$1" '$3==d {print $6, $10}' /proc/diskstats; }

for d in $DEVS; do
    set -- $(read_sectors "$d")
    if [ $# -lt 2 ]; then
        warn "/dev/$d 在 /proc/diskstats 里找不到，跳过"
        continue
    fi
    r0=$1; w0=$2
    sleep 10
    set -- $(read_sectors "$d")
    dr=$(( $1 - r0 ))
    dw=$(( $2 - w0 ))
    info "/dev/$d  10 秒内：读 ${dr} 扇区 / 写 ${dw} 扇区  (= $((dw/2)) KB 写)"
    if [ "$dw" -gt 0 ] || [ "$dr" -gt 0 ]; then
        warn "  盘上有活动 —— 有空闲计时器的话此刻会被清零"
        if [ "$dw" -gt 0 ]; then
            echo "     → 有写入，重点怀疑：ext4lazyinit / 日志 / 做种 / 扫描媒体库"
        else
            echo "     → 只有读取，重点怀疑：媒体库扫描 / 缩略图 / atime 更新"
        fi
    else
        ok "  这 10 秒完全安静，盘是可以进入空闲的"
    fi
done

# ---------- 4. 强制睡 + 观察被唤醒 ----------
hdr "4. 强制入睡测试（hdparm -y，临时生效、无害）"

if [ "$HAVE_HD" != 1 ]; then
    warn "跳过 —— 没有 hdparm，无法下达休眠指令"
    echo "  装上 hdparm 后才能做这一步：opkg update && opkg install hdparm"
else
for d in $DEVS; do
    echo ""
    info "/dev/$d"
    if ! hdparm -y "/dev/$d" >/dev/null 2>&1; then
        bad "  hdparm -y 失败 —— 盒子不接受立即休眠命令"
        continue
    fi

    slept=0; woke=0
    n=0
    while [ "$n" -lt 30 ]; do
        n=$((n+1))
        sleep 2
        st=$(hdparm -C "/dev/$d" 2>/dev/null | sed -n 's/.*drive state is: *//p')
        case "$st" in
            standby|sleep)
                if [ "$slept" -eq 0 ]; then
                    slept=$((n*2))
                    ok "  第 ${slept}s：已进入 standby"
                fi
                woke=0
                ;;
            active*|idle)
                if [ "$slept" -gt 0 ] && [ "$woke" -eq 0 ]; then
                    echo "  第 $((n*2))s：被唤醒回 $st  <-- 有东西在碰盘！"
                    woke=1
                fi
                ;;
            unknown|"")
                if [ "$n" -eq 1 ]; then
                    warn "  状态读不出来（USB 盒子常见，不代表休眠失败）"
                fi
                ;;
        esac
    done

    if [ "$slept" -eq 0 ]; then
        warn "  60 秒观察期内没有读到 standby —— 设备/盒子不上报状态，无法判断"
        echo "     → 用耳朵或手：贴近盘听是否停转、摸温度是否下降"
        echo "     → 或用功率计看瓦数是否从 ~5.5W 掉到 ~1.8W"
    fi
done
fi

# ---------- 5. 嫌疑清单 ----------
hdr "5. 对照排查清单"

cat <<'EOF'
  按出现频率从高到低，逐条核对：

  ▶【首选】SMB 正在被用 —— 只要有人在浏览/读文件，盘就不该睡
      查：smbstatus -b          （谁连着）
          smbstatus -L          （正在读什么）
      说明：走 \\IP\共享名 比映射盘符好，但仍有三种动作会碰盘：
            ① Windows 资源管理器打开该网络位置 → 列目录、刷缩略图、建索引
            ② 播放器/相册软件在扫描媒体文件
            ③ 有任何客户端挂着会话（Samba 会定期保活）
      治法：设长休眠（2~4 小时）而不是几分钟；不用时断开；
            在 [global] 加 deadtime = 5 让空闲会话自动断

  ▶ ext4 延迟初始化（新格式化的盘才有，持续数小时）
      查：cat /proc/mounts | grep -c noinit_itable
      治法：挂载加 noinit_itable，或重格式化时
            mkfs.ext4 -E lazy_itable_init=0,lazy_journal_init=0

  ▶ atime 更新（读文件也写盘）
      查：cat /proc/mounts | grep -o 'relatime\|noatime'
      治法：挂载选项加 relatime（默认通常已是）

  ▶ 上次没正常卸载，重放日志（你盘上 RECOVER 位是亮的）
      查：dmesg | grep -i 'recovery\|orphan\|ext4.*recover'
      治法：正常 umount 一次再挂载，日志重放完就安静了

  ▶ smartd 定时巡检（每几分钟查一次 SMART）
      查：ps | grep -c '[s]martd'
      治法：/etc/init.d/smartd stop && /etc/init.d/smartd disable

  ▶ 下载器在后台做种
      查：ps | grep -E '[q]bittorrent|[t]ransmission|[a]ria2'
      治法：暂停做种，或把做种目录挪到别的盘

  ▶ 媒体库扫描
      查：ps | grep -E '[j]ellyfin|[e]mby|[p]lex|[a]list|[i]mmich'
      治法：关掉"实时监控媒体库变化"，改成定时扫描

  ▶ Docker / 日志
      查：docker ps；ls -la /var/log
      治法：把容器数据目录迁走，或限制日志大小

  ▶ iStoreOS 网页首页会读盘状态
      实测有人反馈"访问 iStoreOS 的图表首页会唤醒所有硬盘"
      治法：别把首页设成收藏，别长期开着后台面板
EOF

echo ""
echo "============================================================"
echo " 体检结束。把上面输出发我，我帮你定具体方案。"
echo "============================================================"
