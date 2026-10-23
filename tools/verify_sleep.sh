#!/bin/sh
# ============================================================
#  verify_sleep.sh  —  快速验证 hdparm -S 是否真的生效
#
#  原理：hdparm 没有读取 -S 值的选项，没法直接查"设成多少了"。
#        所以把时间临时改成 2 分钟，等它自己睡，再用 hdparm -C 看状态。
#        hdparm -C 是 CHECK POWER MODE，只是问"你睡了没"，不会把盘吵醒。
#
#  用法（在 NAS 上以 root 运行）：
#    sh verify_sleep.sh        # 测完恢复成 120 分钟
#    sh verify_sleep.sh 240    # 测完恢复成 240 分钟
#
#  注意：等待期间不要访问共享、不要看 NAS 后台，否则会重置计时器。
#        无论测试成败，结束时都会把休眠时间恢复。
# ============================================================

set -u
RESTORE_MIN="${1:-120}"

# hdparm -S 编码：2 分钟 = 24 × 5 秒
S_FAST=24
if [ "$RESTORE_MIN" -le 20 ]; then
    S_RESTORE=$((RESTORE_MIN * 12))
elif [ "$RESTORE_MIN" -ge 330 ]; then
    S_RESTORE=251
else
    S_RESTORE=$((240 + RESTORE_MIN / 30))
fi

ok()   { echo "  [OK]    $*"; }
warn() { echo "  [注意]  $*"; }
bad()  { echo "  [不可]  $*"; }
info() { echo "  [信息]  $*"; }

if [ "$(id -u)" != "0" ]; then
    echo "请用 root 运行：sudo sh $0 $*"
    exit 1
fi

if ! command -v hdparm >/dev/null 2>&1; then
    bad "没装 hdparm：opkg update && opkg install hdparm"
    exit 1
fi

# ---------- 找盘 ----------
DEV=""
for d in /sys/block/sd*; do
    [ -e "$d" ] || continue
    if grep -qi elements "$d/device/model" 2>/dev/null; then
        DEV=$(basename "$d")
        break
    fi
done
if [ -z "$DEV" ]; then
    warn "没找到 Elements 盘，退回 /dev/sdc"
    DEV=sdc
fi

getstate() {
    hdparm -C "/dev/$DEV" 2>/dev/null | sed -n 's/.*drive state is: *//p'
}

echo "============================================================"
echo " 休眠生效验证（临时设 2 分钟）"
echo "============================================================"
echo ""
info "目标磁盘: /dev/$DEV"
model=$(cat "/sys/block/$DEV/device/model" 2>/dev/null | sed 's/ *$//')
info "型号: ${model:-未知}"
echo ""

S0=$(getstate)
info "当前电源状态: ${S0:-读不到}"
echo ""

# ---------- 设置 2 分钟 ----------
echo "------------------------------------------------------------"
echo " 1. 临时设为 2 分钟空闲休眠"
echo "------------------------------------------------------------"
if ! hdparm -S $S_FAST "/dev/$DEV" >/dev/null 2>&1; then
    bad "设置失败 —— 盒子不透传 ATA 命令，这条路走不通"
    echo ""
    echo "  结论：只能用 hd-idle（且它无法把休眠时间调长）"
    exit 1
fi
ok "已设为 2 分钟（hdparm -S $S_FAST）"
echo ""
warn "接下来 3 分钟内请不要访问共享、不要刷新 NAS 后台"
echo ""

# ---------- 等待并轮询 ----------
echo "------------------------------------------------------------"
echo " 2. 等待它自己睡下去（最多 180 秒）"
echo "------------------------------------------------------------"
i=0
SLEPT_AT=""
while [ "$i" -lt 180 ]; do
    sleep 15
    i=$((i + 15))
    st=$(getstate)
    case "$st" in
        standby|sleep)
            SLEPT_AT=$i
            break
            ;;
        active*|idle)
            echo "  ${i}s ... 还醒着（$st）"
            ;;
        *)
            if [ "$i" -le 15 ]; then
                info "状态读不出来（部分 USB 盒子不上报，不代表失败）"
            fi
            ;;
    esac
done
echo ""

# ---------- 判定 ----------
echo "------------------------------------------------------------"
echo " 3. 结果"
echo "------------------------------------------------------------"
if [ -n "$SLEPT_AT" ]; then
    ok "第 ${SLEPT_AT} 秒进入 standby —— hdparm -S 确实生效了"
    echo ""
    echo "  说明："
    echo "    · 固件计时器真的写进去了，不只是命令返回成功"
    echo "    · 这块盘能自己睡，不需要任何后台服务或插件"
else
    st=$(getstate)
    if [ "$st" = "standby" ] || [ "$st" = "sleep" ]; then
        ok "最终状态 $st —— 生效了（只是轮询没抓到具体时刻）"
    else
        warn "180 秒内没睡下去，当前状态: ${st:-读不到}"
        echo ""
        echo "  可能是这三种情况之一："
        echo "    1. 期间有东西碰了盘（共享窗口开着、后台面板在刷新、远程在拉文件）"
        echo "    2. 盒子接受了命令但没真的执行（USB-SATA 桥接的常见毛病）"
        echo "    3. 状态读不出来（$st 为空或 unknown），只能靠听声音 / 摸温度判断"
        echo ""
        echo "  重测前请先关掉 Windows 上所有打开该共享的窗口和播放器。"
    fi
fi

# ---------- 恢复 ----------
echo ""
echo "------------------------------------------------------------"
echo " 4. 恢复正常休眠时间"
echo "------------------------------------------------------------"
if hdparm -S $S_RESTORE "/dev/$DEV" >/dev/null 2>&1; then
    ok "已恢复为 ${RESTORE_MIN} 分钟（hdparm -S $S_RESTORE）"
else
    bad "恢复失败！请手动执行：hdparm -S $S_RESTORE /dev/$DEV"
fi

echo ""
echo "============================================================"
echo " 验证结束"
echo "============================================================"
