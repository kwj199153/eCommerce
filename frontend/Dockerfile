# ============================================================
#  店管家 AI · 前端镜像（多阶段构建）
# ------------------------------------------------------------
#  构建（在项目根目录）：
#     docker build -f frontend/Dockerfile -t storekeeper-web:latest ./frontend
#
#  为什么用多阶段：
#    第一阶段装 node_modules（含 vite / vue-tsc / typescript）做构建，
#    产物只有 dist/ 静态文件；第二阶段用 nginx 托管。
#    最终镜像里**没有 node_modules**（本项目约 300MB+），只有 ~50MB。
#
#  ★ 构建参数 VITE_* ：Vite 的环境变量是**构建期**注入（编译进 JS bundle），
#    不是运行期读取 —— 改 .env.production 后必须重新 build，重启容器无效。
#    这是「明明改了环境变量却没生效」的最常见原因。
#
#  ★ 关于 VITE_DEMO_MODE：默认走仓库里的 .env.production（=false）。
#    注意代码侧还有一道保险 —— demoMode.ts 里 `import.meta.env.PROD` 为真时
#    无视环境变量强制关闭演示模式，所以生产构建不可能带着 demo-token 直通上线。
# ============================================================

# ---------------- 阶段 1：构建 ----------------
FROM node:22-alpine AS build

WORKDIR /app

# 先只拷清单：依赖没变时这层走缓存，改业务代码不用重装 node_modules
COPY package.json package-lock.json ./
# npm ci 严格按 lock 文件安装（可复现），比 npm install 更适合 CI/发布
RUN npm ci

COPY . .

# 允许在构建时覆盖 Vite 变量，例如：
#   docker build --build-arg VITE_DEMO_MODE=false ...
ARG VITE_DEMO_MODE=false
ARG VITE_VOICE_CLONE_ENABLED=false
ENV VITE_DEMO_MODE=${VITE_DEMO_MODE} \
    VITE_VOICE_CLONE_ENABLED=${VITE_VOICE_CLONE_ENABLED}

# build 脚本 = `vue-tsc && vite build`：类型不过就不出包，
# 避免把「类型已经坏了但还能跑」的产物发上线
RUN npm run build


# ---------------- 阶段 2：托管 ----------------
FROM nginx:1.27-alpine

# 站点配置（含 SPA history 回退、/api 与 /static 反代、gzip、缓存策略）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 构建产物
COPY --from=build /app/dist /usr/share/nginx/html

# nginx 官方镜像默认以 root 启动 master、worker 降权为 nginx 用户。
# 这里额外确保静态目录可读、缓存与 pid 目录存在。
RUN mkdir -p /var/cache/nginx && chown -R nginx:nginx /var/cache/nginx /usr/share/nginx/html

EXPOSE 80

# 健康检查打根路径：SPA 的 / 一定返回 index.html（200）
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
