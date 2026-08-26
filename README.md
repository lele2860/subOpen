# 固定订阅链接临时访问控制

这是一个轻量的 Python 标准库服务，用密码控制一个固定订阅链接的临时访问。

- 订阅链接固定不变，不带 `?token=...`
- 密码验证成功后，公开文件名出现，链接开启 10 分钟
- 到期或点击“提前关闭”后，公开文件名消失，链接返回 HTTP 404
- 关闭时使用可见文件名 `config.disabled.yaml`，更新文件内容时不需要更换订阅地址
- 后端只通过 Docker 映射到本机 `127.0.0.1:18080`
- 不需要 Python 第三方依赖

## 工作方式

例如配置如下：

~~~ini
FILE_PATH=/data/config.yaml
LOCKED_FILE_PATH=/data/config.disabled.yaml
SUB_PATH=/sub/你的固定订阅路径
~~~

关闭访问时文件名为 `config.disabled.yaml`。密码验证成功后，同一个文件临时改名为 `config.yaml`；10 分钟到期或手动关闭后再改回 `config.disabled.yaml`。两个文件名都能在 Xftp 中直接看到。

固定链接没有单独的 token。也就是说，只要有人知道这个固定链接，就可以在当前 10 分钟窗口内访问；这是“不使用 token”带来的行为。

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

不要把真实的 `config/gate.conf` 提交到 GitHub。该文件包含访问密码，仓库只提供示例配置。

当前服务没有公网改密接口。修改密码应通过 SSH 编辑服务器上的配置文件，然后重启服务。

## 在现有服务器上迁移到 Docker

下面的步骤适用于 Nginx 已经代理 `127.0.0.1:18080` 的服务器。

### 1. 获取项目

~~~bash
git clone https://github.com/lele2860/subOpen.git /opt/subscription-gate
cd /opt/subscription-gate
~~~

### 2. 准备订阅目录

服务需要在订阅目录内创建、删除临时公开文件名，因此目录必须允许容器内的 `www-data`（UID/GID 33）写入。下面以当前目录 `/var/www/mihomo` 为例：

~~~bash
systemctl stop subscription-gate

# 只在 config.disabled.yaml 还不存在时执行，避免覆盖已有文件
test ! -e /var/www/mihomo/config.disabled.yaml
mv /var/www/mihomo/config.yaml /var/www/mihomo/config.disabled.yaml

chown root:www-data /var/www/mihomo /var/www/mihomo/config.disabled.yaml
chmod 775 /var/www/mihomo
chmod 640 /var/www/mihomo/config.disabled.yaml
~~~

### 3. 创建 Docker 配置

~~~bash
mkdir -p config
cp config/gate.conf.example config/gate.conf
sed -i \
  -e 's#^PASSWORD=.*#PASSWORD=替换为你的访问密码#' \
  -e 's#^FILE_PATH=.*#FILE_PATH=/data/config.yaml#' \
  -e 's#^LOCKED_FILE_PATH=.*#LOCKED_FILE_PATH=/data/config.disabled.yaml#' \
  -e 's#^SUB_PATH=.*#SUB_PATH=/sub/你的固定订阅路径#' \
  config/gate.conf
chmod 640 config/gate.conf
~~~

确认配置至少包含：

~~~ini
PASSWORD=你的访问密码
FILE_PATH=/data/config.yaml
LOCKED_FILE_PATH=/data/config.disabled.yaml
SUB_PATH=/sub/你的固定订阅路径
BIND=0.0.0.0
PORT=8080
TTL_SECONDS=600
~~~

### 4. 启动 Docker

旧 systemd 服务和 Docker 不能同时占用 18080 端口：

~~~bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 subscription-gate
curl -sS http://127.0.0.1:18080/healthz
~~~

看到 `ok` 即表示后端正常。

### 5. 配置 Nginx

HTTPS server 中需要包含 `deploy/nginx-subscription.conf.example` 的三个 location，并将最后一个 location 的路径替换成 `gate.conf` 中的 `SUB_PATH`。

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

输入密码后复制固定订阅链接到订阅客户端。链接中不会出现 `token=`，以后重新输入密码仍然使用同一个地址。

登录成功后，页面下方会显示在线 YAML 编辑器。可以直接修改订阅内容并点击“保存配置”；保存接口只接受当前密码会话，并且只在 10 分钟访问窗口内可用。编辑会话使用 HttpOnly Cookie，不会出现在订阅链接中。

## 新环境部署

~~~bash
git clone https://github.com/lele2860/subOpen.git /opt/subscription-gate
cd /opt/subscription-gate
mkdir -p data config
cp /path/to/config.yaml data/config.disabled.yaml
chown -R 33:33 data
chmod 770 data
chmod 640 data/config.disabled.yaml
cp config/gate.conf.example config/gate.conf
~~~

编辑 `config/gate.conf`：

~~~ini
PASSWORD=请替换为随机密码
FILE_PATH=/data/config.yaml
LOCKED_FILE_PATH=/data/config.disabled.yaml
SUB_PATH=/sub/你的固定订阅路径
BIND=0.0.0.0
PORT=8080
TTL_SECONDS=600
~~~

启动：

~~~bash
docker compose up -d --build
~~~

## 修改密码

服务器上编辑配置文件：

~~~bash
nano /opt/subscription-gate/config/gate.conf
~~~

只修改 `PASSWORD`，然后重启服务：

~~~bash
docker compose restart subscription-gate
~~~

重启会关闭当前订阅访问，但不会改变固定订阅链接。

如果当前使用的是 systemd：

~~~bash
nano /etc/subscription-gate/gate.conf
systemctl restart subscription-gate
~~~

## 回滚到 systemd

~~~bash
docker compose down
systemctl enable --now subscription-gate
~~~

Nginx 仍使用 `127.0.0.1:18080`，通常不需要修改 Nginx 配置。

## API

~~~text
POST /sub-access/api/login
body: {"password":"..."}
返回的 url 是固定的 SUB_PATH，不带 token

GET /sub-access/api/file
读取当前订阅内容，需要登录后的浏览器会话

POST /sub-access/api/file
body: {"content":"..."}
保存订阅内容，最大 2 MB，需要登录后的浏览器会话

POST /sub-access/api/revoke
无需请求体，需要登录后的浏览器会话
~~~

没有公网修改密码 API；密码修改应通过 SSH 或受控的服务器配置管理流程完成。

