#builder镜像
FROM python:3.10.13-bullseye as builder
#FROM python:3.9.4-buster as builder

WORKDIR /usr/src/app

# 加速安装
#COPY docker/sources.list /etc/apt/sources.list
RUN  echo "deb https://mirrors.aliyun.com/debian/ bullseye main non-free contrib \
  deb-src https://mirrors.aliyun.com/debian/ bullseye main non-free contrib \
  deb https://mirrors.aliyun.com/debian-security/ bullseye-security main \
  deb-src https://mirrors.aliyun.com/debian-security/ bullseye-security main \
  deb https://mirrors.aliyun.com/debian/ bullseye-updates main non-free contrib \
  deb-src https://mirrors.aliyun.com/debian/ bullseye-updates main non-free contrib \
  deb https://mirrors.aliyun.com/debian/ bullseye-backports main non-free contrib \
  deb-src https://mirrors.aliyun.com/debian/ bullseye-backports main non-free contrib" | tee  /etc/apt/sources.list


RUN apt update && \
  apt install -y swig tzdata \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

ENV TZ Asia/Shanghai

RUN pip install \
  -i http://mirrors.aliyun.com/pypi/simple \
  --trusted-host mirrors.aliyun.com/pypi/simple/ \
  --upgrade pip setuptools wheel pyarmor==8.3.11


COPY . .

# 6.1 生成加密文件
RUN pyarmor gen main.py config.py ./utils

#实际运行镜像
FROM python:3.10.13-bullseye
#FROM python:3.9.4-buster

WORKDIR /app

# 设置时区
ENV TZ Asia/Shanghai

# 设置 PYTHONPATH，让 Python 能找到 cosyvoice 包
ENV PYTHONPATH="/app/CosyVoice:${PYTHONPATH}"

# 禁用 transformers 自动加载 deepspeed
ENV TRANSFORMERS_NO_DEEPSPEED=1

# 加速安装
#COPY docker/sources.list /etc/apt/sources.list
RUN  echo "deb https://mirrors.aliyun.com/debian/ bullseye main non-free contrib \
  deb-src https://mirrors.aliyun.com/debian/ bullseye main non-free contrib \
  deb https://mirrors.aliyun.com/debian-security/ bullseye-security main \
  deb-src https://mirrors.aliyun.com/debian-security/ bullseye-security main \
  deb https://mirrors.aliyun.com/debian/ bullseye-updates main non-free contrib \
  deb-src https://mirrors.aliyun.com/debian/ bullseye-updates main non-free contrib \
  deb https://mirrors.aliyun.com/debian/ bullseye-backports main non-free contrib \
  deb-src https://mirrors.aliyun.com/debian/ bullseye-backports main non-free contrib" | tee  /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ffmpeg vim tzdata openssh-server portaudio19-dev libportaudio2 libportaudiocpp0 numactl libgomp1 \
 && mkdir /var/run/sshd \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# RUN pip install --no-cache-dir py-cpuinfo psutil
# 复制 Python requirements 并安装
COPY requirements_v.txt ./
RUN pip install --no-cache-dir -r requirements_v.txt

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制原始程序源码
COPY ./config        /app/config/

# 复制加密生成的 dist 文件
COPY --from=builder /usr/src/app/dist /app

CMD [ "python", "./main.py" ]
