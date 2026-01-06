# PTP 网络查看指南

本指南介绍如何查看和监控 PTP (Precision Time Protocol) 网络状态。

## 🚀 快速查看工具

### 1. 一键查看脚本

```bash
# 查看 PTP 服务状态和同步信息
sudo ./scripts/ptp_status.sh

# 查看 PTP 网络拓扑和设备
sudo ./scripts/ptp_network.sh
```

## 📋 手动查看命令

### 基本状态查看

```bash
# 查看服务状态
sudo systemctl status ptp4l-client

# 实时查看同步日志
sudo journalctl -u ptp4l-client -f

# 查看最近日志
sudo journalctl -u ptp4l-client -n 50
```

### PTP 管理客户端 (pmc)

```bash
# 查看当前同步数据（时钟偏移、路径延迟）
sudo pmc -u -b 0 'GET CURRENT_DATA_SET'

# 查看主时钟信息
sudo pmc -u -b 0 'GET PARENT_DATA_SET'

# 查看时间状态
sudo pmc -u -b 0 'GET TIME_STATUS_NP'

# 查看端口状态
sudo pmc -u -b 0 'GET PORT_DATA_SET'

# 查看默认数据集（本地时钟信息）
sudo pmc -u -b 0 'GET DEFAULT_DATA_SET'
```

### 硬件时钟查看

```bash
# 查看 PTP 硬件时钟
ls -l /dev/ptp*

# 读取硬件时钟时间
sudo phc_ctl /dev/ptp0 get

# 查看网卡硬件时间戳能力
ethtool -T eno1
```

### 网络抓包

```bash
# 抓取 PTP 报文 (Ethernet)
sudo tcpdump -i eno1 -vv ether proto 0x88f7

# 抓取 PTP 报文 (UDP)
sudo tcpdump -i eno1 -vv udp port 319 or udp port 320

# 保存到文件
sudo tcpdump -i eno1 -w ptp_capture.pcap ether proto 0x88f7
```

## 📊 关键性能指标

### 日志输出解释

```
ptp4l[17307.034]: rms 396 max 604 freq -5148 +/- 451 delay 1924 +/- 7
```

- **rms**: 均方根误差（纳秒），越小越好，通常 <1000 ns
- **max**: 最大偏差（纳秒）
- **freq**: 频率偏移（ppb，十亿分之一）
- **delay**: 网络路径延迟（纳秒）

### 同步状态

- **LISTENING**: 监听状态，等待主时钟
- **UNCALIBRATED**: 检测到主时钟，开始校准
- **SLAVE**: 已同步，作为从时钟运行
- **MASTER**: 作为主时钟运行

## 🔍 PTP 网络信息

### 当前配置

- **本地设备 ID**: 3c6d66.fffe.4ea8d5
- **主时钟 ID**: 3484e4.fffe.ca6c1a
- **网络接口**: eno1 (192.168.0.200)
- **同步精度**: ~500 ns (亚微秒级)
- **跳数**: 1 hop (直连主时钟)

### 网络拓扑

```
GrandMaster (3484e4.fffe.ca6c1a)
    ClockClass: 6 (高精度时钟)
         ↓
    [1 hop]
         ↓
This Device (3c6d66.fffe.4ea8d5)
    Interface: eno1
    IP: 192.168.0.200
    Status: SLAVE
```

## 🛠️ 故障排查

### 检查列表

1. **服务是否运行？**
   ```bash
   sudo systemctl status ptp4l-client
   ```

2. **是否发现主时钟？**
   ```bash
   sudo pmc -u -b 0 'GET PARENT_DATA_SET' | grep grandmaster
   ```

3. **端口状态是否为 SLAVE？**
   ```bash
   sudo pmc -u -b 0 'GET PORT_DATA_SET' | grep portState
   ```

4. **网络接口是否正常？**
   ```bash
   ip link show eno1
   ethtool -T eno1
   ```

5. **是否有 PTP 流量？**
   ```bash
   sudo tcpdump -i eno1 -c 10 udp port 319
   ```

## 📈 性能优化建议

- 确保使用硬件时间戳（hardware timestamping）
- 减少网络跳数
- 使用专用网络或 VLAN
- 避免网络拥塞
- 定期检查同步精度

## 🔗 相关文件

- 配置文件: `config/ptp/ptp_client.conf`
- 服务文件: `config/ptp/ptp4l-client.service`
- 状态脚本: `scripts/ptp_status.sh`
- 网络脚本: `scripts/ptp_network.sh`
