FROM node:20-alpine AS builder
WORKDIR /app

# 设置 npm 镜像源为淘宝镜像（加速下载）
RUN npm config set registry https://registry.npmmirror.com

# 只拷贝依赖文件（利用 Docker 缓存层）
COPY package.json package-lock.json* ./

# 使用 npm ci 替代 npm install（更快更可靠）
# 如果没有 package-lock.json，会自动降级使用 npm install
RUN if [ -f package-lock.json ]; then \
        npm ci; \
    else \
        npm install; \
    fi

# 拷贝其余源码
COPY . .

# 构建项目
RUN npm run build

# 生产阶段
FROM nginx:alpine

# 更换 Alpine 源为阿里云（加速 nginx 镜像的依赖安装）
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

# 拷贝构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 拷贝 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]