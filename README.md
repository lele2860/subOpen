# 临时订阅访问控制 Docker 部署

这是一个轻量的 Python 标准库服务，用密码开启一个配置文件的临时访问链接。

- 同一个配置文件始终使用同一个 LINK_TOKEN
- 密码验证成功后，链接开启 10 分钟
- 页面显示倒计时，并支持提前关闭
- 到期或关闭后，链接返回 HTTP 403
- 后端只通过 Docker 映射到本机 127.0.0.1:18080
- 不需要 Python 第三方依赖

## 目录结构

~~~text
.
├── Dockerfile
├── docker-compose.yml
├── subscription_gate.py
├── config/
│   └── gate.conf.example
└── deploy/
    └── nginx-subscription.conf.example
~~~

## 安全说明

不要把真实的 config/gate.conf 提交到 GitHub。该文件包含访问密码和固定链接令牌，仓库只提供 gate.conf.example。

当前服务没有公网改密接口。修改密码应通过 SSH 编辑服务器上的 config/gate.conf，然后重启容器。修改密码时不要修改 LINK_TOKEN，否则订阅客户端保存的链接也会改变。

## 在现有服务器上迁移到 Docker

下面的步骤适用于当前 Nginx 已经代理 127.0.0.1:18080 的服务器。

### 1. 获取项目

~~~bash
git clone https://github.com/lele2860/subOpen.git /opt/subscription-gate
cd /opt/subscription-gate
~~~

### 2. 从现有 systemd 服务迁移配置

这一步会保留现有密码、固定链接令牌和订阅路径，不要把生成后的配置提交到 Git。

~~~bash
mkdir -p config
cp /etc/subscription-gate/gate.conf config/gate.conf
sed -i \
  -e 's#^FILE_PATH=.*#FILE_PATH=/data/config.yaml#' \
  -e 's#^BIND=.*#BIND=0.0.0.0#' \
  -e 's#^PORT=.*#PORT=8080#' \
  config/gate.conf
chmod 640 config/gate.conf
~~~

确认配置里至少包含：

~~~ini
PASSWORD=原来的访问密码
LINK_TOKEN=原来的固定链接令牌
FILE_PATH=/data/config.yaml
SUB_PATH=/sub/你的订阅路径
BIND=0.0.0.0
PORT=8080
TTL_SECONDS=600
~~~

确认订阅文件可被容器内的 www-data 读取：

~~~bash
stat -c '%a %U:%G' /var/www/mihomo/config.yaml
~~~

如果文件是 root:www-data 且权限为 640，可以直接使用；如果是 600 root:root，需要调整为：

~~~bash
chown root:www-data /var/www/mihomo/config.yaml
chmod 640 /var/www/mihomo/config.yaml
~~~

### 3. 停止旧服务并启动 Docker

旧 systemd 服务和 Docker 不能同时占用 18080 端口：

~~~bash
systemctl disable --now subscription-gate
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 subscription-gate
curl -sS http://127.0.0.1:18080/healthz
~~~

看到 ok 即表示容器后端正常。

### 4. 配置 Nginx

Nginx HTTPS server 中需要包含 deploy/nginx-subscription.conf.example 的三个 location，并将最后一个 location 的路径替换成 gate.conf 中的 SUB_PATH。

必须删除或替换原来直接暴露订阅文件的配置，例如：

~~~nginx
alias /var/www/mihomo/config.yaml;
~~~

检查并重载：

~~~bash
nginx -t
systemctl reload nginx
~~~

然后打开：

~~~text
https://你的域名/sub-access/
~~~

输入密码后复制临时链接到订阅客户端。以后重新输入密码会重新开启同一个链接，不需要在客户端更换订阅地址。

## 新环境部署

~~~bash
cp config/gate.conf.example config/gate.conf
mkdir -p data
cp /path/to/config.yaml data/config.yaml
~~~

编辑 config/gate.conf：

~~~ini
PASSWORD=请替换为随机密码
LINK_TOKEN=请替换为至少 32 位随机令牌
FILE_PATH=/data/config.yaml
SUB_PATH=/sub/你的订阅路径
BIND=0.0.0.0
PORT=8080
TTL_SECONDS=600
~~~

可用 OpenSSL 生成随机值：

~~~bash
openssl rand -hex 24
~~~

启动：

~~~bash
SUBSCRIPTION_FILE="$PWD/data/config.yaml" docker compose up -d --build
~~~

## 修改密码

服务器上编辑：

~~~bash
nano /opt/subscription-gate/config/gate.conf
~~~

只修改 PASSWORD，然后：

~~~bash
cd /opt/subscription-gate
docker compose restart subscription-gate
~~~

重启会让当前已开启的 10 分钟访问立即失效，但不会改变固定订阅链接。

## 回滚到 systemd

~~~bash
docker compose down
systemctl enable --now subscription-gate
~~~

Nginx 仍使用 127.0.0.1:18080，通常不需要修改 Nginx 配置。

## API

~~~text
POST /sub-access/api/login
body: {"password":"..."}

POST /sub-access/api/revoke
body: {"token":"..."}
~~~

没有公网修改密码 API；密码修改应通过 SSH 或受控的服务器配置管理流程完成。
