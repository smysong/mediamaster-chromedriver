# 使用 Ubuntu 24.04 作为基础镜像
FROM ubuntu:24.04

# 设置工作目录
WORKDIR /app

# 检测 CPU 架构并更新软件包列表并安装必要的软件包
RUN ARCH=$(uname -m) && \
    apt-get update && \
    apt-get install -y curl unzip python3-pip python3-venv cron wget fonts-liberation && \
    if [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "aarch64" ]; then \
        apt-get install -y libasound2-plugins libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
                           libcairo2 libcups2 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
                           libpango-1.0-0 libvulkan1 libxcomposite1 libxdamage1 libxext6 \
                           libxfixes3 libxkbcommon0 libxrandr2 xdg-utils; \
    fi && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 设置系统语言为简体中文
RUN apt-get update -y && \
    apt-get install -y locales && \
    locale-gen zh_CN.UTF-8 && \
    update-locale LANG=zh_CN.UTF-8 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 设置时区为中国时区
RUN apt-get update -y && \
    apt-get install -y tzdata && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安装 Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
&& sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
&& apt-get update \
&& apt-get install -y google-chrome-stable \
&& rm -rf /var/lib/apt/lists/*

# 下载并配置 ChromeDriver
RUN CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+\.\d+') \
&& CHROME_DRIVER_VERSION=$(curl -sS "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_VERSION%.*}") \
&& wget -N "https://chromedriver.storage.googleapis.com/${CHROME_DRIVER_VERSION}/chromedriver_linux64.zip" \
&& unzip chromedriver_linux64.zip \
&& mv chromedriver /usr/local/bin/ \
&& chmod +x /usr/local/bin/chromedriver \
&& rm chromedriver_linux64.zip

# 创建虚拟环境
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm requirements.txt

# 安装 schedule 库
RUN pip install schedule

# 创建设置 ulimit 的脚本
COPY set_ulimits.sh /app/
RUN chmod +x /app/set_ulimits.sh

# 复制 Python 脚本
COPY tvshow_downloader.py .
COPY movie_downloader.py .
COPY actor_nfo.py .
COPY episodes_nfo.py .
COPY manual_search.py .
COPY settings.py .
COPY app.py .
COPY check_rss.py .
COPY rss.py .
COPY scan_media.py .
COPY sync.py .
COPY tmdb_id.py .

# 复制 html 模板
COPY templates.zip .
RUN unzip templates.zip -d /app/ && \
    rm templates.zip

# 创建定时任务脚本
COPY main.py .

# 运行定时任务脚本
CMD ["python", "main.py"]

# 声明监听端口
EXPOSE 8888