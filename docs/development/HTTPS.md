# HTTPS 入口与证书维护

用户入口：**https://42.193.15.167**。2026-09-08 已上线，用户无需 SSH、域名或手动信任证书，登录后可直接录入个人 API Key。首次改用 HTTPS 需要重新登录原账号，账号、聊天与文件数据不变。

## 端口与转发

- 公网 443：nginx 提供 TLS，反向代理至 `127.0.0.1:9119`。
- 公网 80：仅证书验证路径提供静态文件，其他请求 308 跳转 HTTPS。
- 原公网 9119：nginx 绑定服务器默认路由的本机 IPv4 地址并跳转 HTTPS；应用只监听 `127.0.0.1:9119`，原运维脚本的内部地址继续可用。
- Agent 仍只监听 `127.0.0.1:8642`；其他 nginx 站点和服务端口保留。

nginx 支持 WebSocket Upgrade，关闭代理响应缓冲以保留模型流式输出，不额外限制上传大小。转发的 HTTPS 协议头由 nginx 固定设置，后端仅信任 `127.0.0.1` 的代理头。登录和会话 Cookie 启用 Secure，持久配置中的公开 URL 同步更新。

## 证书与自动续期

证书由 Let's Encrypt 正式 CA 签发，SAN 为 IP `42.193.15.167`，不是自签名证书。IP 证书使用约六天的有效期；本次证书有效期至 2026-09-14，日常无需手动申请。

| 内容 | 服务器位置 |
| --- | --- |
| nginx 配置 | `/etc/nginx/conf.d/haudi-workstation-https.conf` |
| 证书与私钥 | `/etc/haudi-letsencrypt/live/workstation-ip/` |
| 验证文件根目录 | `/var/lib/haudi-acme/` |
| 独立 Certbot 5.4.0 环境 | `/home/ubuntu/haudi-hermes/certbot-venv/` |
| 定时任务 | `haudi-certificate-renew.timer` / `.service` |
| 续期重载脚本 | `/usr/local/sbin/haudi-certificate-reloaded` |
| 证书日志 | `/var/log/haudi-letsencrypt/` |
| 部署备份位置记录 | `openwebui/https-deployment.json` |

定时器每六小时检查一次，加入最多 15 分钟随机延迟，错过的检查在启动后补跑。证书到续期窗口时自动续签；成功后先验证 nginx 配置，再平滑重载。**保持云防火墙的 TCP 80 / 443 开放**，否则证书验证或网页访问会失败。证书私钥、账户目录、环境文件和数据卷均不提交源码仓库。

```bash
sudo systemctl list-timers haudi-certificate-renew.timer
sudo systemctl start haudi-certificate-renew.service
sudo journalctl -u haudi-certificate-renew.service --since '2 days ago'
sudo openssl x509 -in /etc/haudi-letsencrypt/live/workstation-ip/fullchain.pem -noout -dates
```

## 发布与回退

按顺序执行 `deploy/hermes/prepare-https.sh`、`issue-https-certificate.sh`，然后上传 `activate-https.py` 并在服务器以 root 执行。申请脚本先做测试 CA 演练，再申请正式证书；安装使用独立虚拟环境，不改变 Agent 依赖。

切换脚本备份应用环境与 nginx 配置，保留旧容器；新后端、TLS 证书或健康检查失败时恢复旧配置和容器。成功后 `openwebui/https-deployment.json` 记录备份与回退容器。证书续期单独运行，不需要重建 UI 镜像。

本次回退容器为 `haudi-openwebui-before-https-20260908T055523Z`。手动回退应先恢复备份的 nginx 配置并重载，释放公网 9119 监听，再恢复环境文件与旧容器，最后恢复 `webui.url`。不要只启动旧容器，否则会与 nginx 的 9119 监听冲突。

服务器直连 PyPI 较慢时，可从官方 PyPI 下载 Linux Python 3.12 的 wheels，上传后用 `uv pip install --no-index --find-links <目录>` 安装；不要将这些构建缓存加入 Git。

## 验收

已从服务器外验证可信证书与公网 443、旧 9119 跳转；浏览器正常登录且 `window.isSecureContext` 为 true，Key 输入框可用。HTTPS 下真实 DeepSeek Key 保存验证成功，Flash / Pro 流式回复与 Agent 记录中的实际模型一致，临时测试 Key 已删除。安全 WebSocket 握手成功。

`verify-https.sh` 已完成续期演练及部署 hook 测试；实际 systemd 续期服务返回成功，定时器处于 active 状态。验收时未跳过 TLS 证书校验。

依据：[Let's Encrypt 官方 IP 证书与 Certbot 配置说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。
