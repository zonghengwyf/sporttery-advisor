FROM python:3.11-slim

WORKDIR /app

# 清理旧apt源，换国内阿里源
RUN rm -rf /etc/apt/sources.list.d/* && \
echo "deb https://mirrors.aliyun.com/debian trixie main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
echo "deb https://mirrors.aliyun.com/debian trixie-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
echo "deb https://mirrors.aliyun.com/debian-security trixie-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

# 系统依赖
RUN apt-get update && apt-get install -y \
    curl wget gnupg \
    && rm -rf /var/lib/apt/lists/*

# pip国内镜像
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装构建工具
RUN pip install --no-cache-dir hatchling

# 【关键分层】先拷贝 pyproject.toml 和必要文件，利用缓存
COPY pyproject.toml .
# 如果项目需要 __init__.py 文件来安装，先创建占位
RUN mkdir -p sporttery_advisor_backend && \
    touch sporttery_advisor_backend/__init__.py

# 安装依赖（这样会在 /app 目录下安装包）
RUN pip install --no-cache-dir -e .

# playwright国内下载
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
RUN playwright install chromium --with-deps

# 最后拷贝全部业务代码
COPY . .

RUN mkdir -p /data/snapshots

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]