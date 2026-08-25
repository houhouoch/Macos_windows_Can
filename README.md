# Macos Windows CAN Bridge

这个仓库用于让 macOS 开发机通过局域网 SSH 调用 Windows CAN 测试机。Windows 连接 CANalyst-II，使用厂商 `ControlCAN.dll` 监听物理 CAN1；测试结果通过 SCP 返回 Mac，不提交到公开 GitHub 仓库。

## 当前固定配置

- Windows 主机：`LAPTOP-4AQITE36`
- Windows 地址：`192.168.8.19`
- Windows 用户：`admin`
- Windows 仓库：`C:\work\Macos_windows_Can`
- CAN 设备：`VID_04D8&PID_0053`
- 物理通道：CAN1，对应厂商 API 索引 `0`
- CAN 模式：正常模式
- 波特率：`1,000,000 bit/s`

## 安全边界

- SSH 防火墙规则只允许 Windows Private 网络的 `LocalSubnet`。
- Mac 使用独立 SSH 私钥 `~/.ssh/udp3900_windows`；私钥不得提交或复制到 Windows。
- `vendor/`、CAN 抓包、日志和测试结果都被 `.gitignore` 排除。
- 仓库是公开仓库，因此测试证据只通过 SSH/SCP 传输。

## Mac 首次配置

```bash
cp config/windows-host.example.env config/windows-host.env
./tools/macos/check_windows_host.sh
```

## 执行 CAN 测试

从本仓库运行：

```bash
./tools/macos/dispatch_windows_can_test.sh \
  --firmware-repo /Users/houhou/udp3900 \
  --commit HEAD \
  --seconds 15
```

调度器拒绝绑定脏工作区：CAN 证据必须标记一个明确、已推送到 `origin/main` 的固件 commit。执行调度前，必须先在 Mac 上构建并烧录该 commit。CAN 分析仪不能独立读取或证明开发板中的 Git commit，因此 `result.json` 会明确把它记录为调度器标签，而不是硬件验证值。

Windows 会拉取本桥接仓库、下载本地测试所需的 `Can_analyze` 厂商 DLL 副本、监听 CAN1，并把 ZIP 结果传回：

```text
artifacts/windows-can/<firmware-commit>/<timestamp>/
├── frames.csv
└── result.json
```

`result.json` 中的 `frame_count` 大于零，才证明 Windows CAN 分析仪收到了物理总线帧。
