
## 安装依赖
```bash
pip install -r requirements.txt 
````

# 使用版本
# 微信自动化库: pywechat127 (pyweixin 模块)
# GitHub: https://github.com/Hello-Mr-Crab/pywechat
# 安装: pip install pywechat127 --user --no-cache-dir
# 适配微信版本: 4.1.x
# Python: >=3.10
# {'exe路径': 'D:\\software\\Weixin\\Weixin.exe', '版本': '4.1.8.107', '语言': '简体中文', 'wxid': 'wxid_eunjbg9vzjdr22_316', 'wxid目录': 'C:\\Users\\march\\xwechat_files\\wxid_eunjbg9vzjdr22_316b', '微信配置目录': 'D:\\software\\Weixin\\4.1.8.107', '聊天文件目录': 'C:\\Users\\march\\xwechat_files\\wxid_eunjbg9vzjdr22_316b\\msg\\file'}


# 后期备选路线
# wxauto4 文档： https://docs.wxauto.org/docs/install.html
# pip install wxauto4 # Name: wxauto4   # Version: 41.1.2 (已弃用，改用 pywechat127)
# 微信版本 weixin_4.1.8.107

# 不能拷贝之前的消息然后回复消息，使用测试群最后一条消息当最新接收的消息做信息的拷贝和回复测试，代码调整，尽量简化代码

# WeChatFerry, weilink， 不要垃圾


新加的功能：
0 最后完整给大模型的提示词 写入日志， 方便后期查日志 
1 把实时放到提示词里面去， 需要知道实时时间， 年月日时分秒。
2 检测到新的消息的时候，拷贝对话里面最近的5条消息一起放入提示词。
3 把最近所有的聊天信息一起放入提示词， 然后做回答， 需要记忆。
4 切换模型， 需要能够读取图片信息的模型，测试settings里面的 https://ark.cn-beijing.volces.com/api/v3 对应的模型，多模态，改 password.yaml 模型名称。 
5 长期习惯，爱好，需要保存到persona.yaml，做长期保留， 提示词区别长期记忆和最近的对话， 实际聊天的时候一起放入提示词里面去。

自测：
1 调整完成后，自己先做测试，使用测试群测试能否读取5条信息，
2 看是否提示词里面有实时时间，年月日时分秒
3 测试能否读到图片的信息。 使用和三月的对话的最后一条消息测试能否识别图片， 能识别就行， 不能回复， 不然后续测试不了。
4 保存需要长期记忆的信息到 persona.yaml 里面的长期记忆 关键词下面，对话完成后，实时更新这个yaml文件， 测试直接读取这个文件看是否改成功这个文件。 

注意，不要有太多冗余代码， 代码要简洁。 

# 触发新消息的时候获取最近5条消息的逻辑没有正常触发， 都重复拿了最后一条消息， 调整逻辑， 看下最后拿到的数据可以知道是否重复拿一条消息。


# 根据定时任务配置，每次更改文件触发下配置文件检测，使用最新的配置文件更新定时任务。
# 定时发送消息到指定群。 
# 配置逻辑： 定时任务时分秒 要回复的会话, 发送的消息, 如 '0 8 * * *': ['二人世界🌍（备婚版）', '爸爸妈妈 早上好！']

触发定时任务的时候，把消息先给大模型处理下，不要很僵硬的回复早上好，晚上好这种。
早上好的时候 先算下命，如运势怎么样，应该注意啥之类的。


  •  记录 大家所有的生活习惯存历史数据  生活习惯  爱好 
  •  对话按时间和信息放到数据库
  •  读取图片和语音


具体功能
1 微信定时在群里发消息， 早安晚安
2 根据定义的身份信息 在群里面聊天， 调用大模型回复， 后台配置对应的接口
3 定时 在群里发送生日提醒
4 可以和群里其他人聊天
有开发经验，需要高拓展性，会配置很聪明的模型来回答，如最新的chatgpt的模型接口， 给个推荐开发起来比较快的方式
使用新的手机注册的微信号来做群聊的机器人


是本地部署一个微信 AI 群聊机器人（数字人）。你的功能列表已经接近一个完整的 Agent 系统。
考虑你有开发经验，并且希望：
接入最新 ChatGPT 类模型
高可扩展
自己控制身份、人设、记忆
新微信号作为机器人账号
快速开发
我建议不要从微信协议底层硬搞，而采用：
微信客户端自动化层 + Bot 框架 + Agent 后端 + LLM 网关
整体架构：
微信群
|
微信机器人账号
|
┌─────────┴─────────┐
│ 微信接入层 │
│ (监听消息/发送消息) │
└─────────┬─────────┘
|
Bot服务
|
┌─────────┴─────────┐
│ Agent核心 │
│ - 人设 │
│ - 记忆 │
│ - 意图判断 │
│ - 工具调用 │
└─────────┬─────────┘
|
┌─────────┴─────────┐
│ 大模型接口 │
│ GPT / Claude / 国产 │
└───────────────────┘
方案推荐（开发速度优先）
方案 A（推荐）：微信机器人 + Python + OpenAI API
技术栈：
模块 推荐
语言 Python
微信接入 微信 PC 自动化 / 无头客户端
机器人框架 NoneBot2 / 自研
后台 FastAPI
数据库 PostgreSQL
缓存 Redis
向量记忆 Qdrant / Milvus
任务调度 APScheduler
模型 GPT-5.x API / Claude / Gemini 豆包
1. 微信接入层
你的新微信号：
微信号A
|
加入多个微信群
|
机器人程序监听消息
负责：
收群消息
判断是否@机器人
发送回复
定时发送
推荐方式：
Windows电脑运行微信 + 自动化
例如：
itchat（简单）
wxauto（目前个人项目常用）
WeChatFerry（功能强）
结构：
Windows
|
微信客户端
|
wxauto
|
Python Bot
优点：
开发快
调试方便
接近真人微信
缺点：
依赖微信客户端在线
2. 机器人核心设计
不要把逻辑写死。
设计 Agent：


整体架构：
├── main.py
|
├── agent/
│ ├── persona.py
│ ├── memory.py
│ ├── planner.py
│
├── tools/
│ ├── birthday.py
│ ├── scheduler.py
│
├── llm/
│ ├── openai.py
│
└── config/
└── basic_config/settings.yaml

功能实现设计
功能1：每天早安晚安
不要写：
if 8点:
发送早安
设计：
任务系统：
Scheduler
每天08:00
调用:
MorningMessageGenerator
↓
GPT生成:
"早上好，今天北京天气不错..."
↓
发送微信群
代码类似：
@scheduler.daily("08:00")
def morning():
msg = agent.chat(
"""
生成一句早安群消息
人设:
阳光幽默
"""
)
wx.send_group(
"朋友群",
msg
)
功能2：根据身份聊天
核心是 Persona。
例如：
config/persona.yaml
name: 小龙虾
age: 28
identity:
一个懂技术的朋友
style:
- 幽默
- 偶尔开玩笑
- 不机械
knowledge:
- 编程
- AI
- 日常聊天
rules:
- 不透露自己是机器人
- 回复自然
然后每次请求：
System Prompt:
你叫小龙虾
你的身份:
xxx
聊天风格:
xxx
用户:
你好
功能3：生日提醒
数据库：
birthday表
name birthday group
张三 1995-06-01 技术群
李四 1998-08-10 朋友群
每天：
凌晨任务
查询:
今天生日的人
↓
GPT生成:
"今天是张三生日，
大家祝他生日快乐🎂"
↓
微信群发送
功能4：群聊
流程：
群消息：
小明:
最近AI发展怎么样？
机器人收到：
↓
判断：
是否需要回复?
不要每句话回复。
增加策略：
reply_probability = 0.15
例如：
普通聊天：
10%-20%概率插话
被@：
100%回复
关键词：
AI
GPT
机器人
小龙虾
立即回复。
关键：记忆系统
如果想“聪明”，必须有记忆。
不要：
用户消息
↓
GPT
↓
回复
应该：
用户消息
↓
提取信息
↓
存储
↓
下一次调用
例如：
用户：
我下个月去上海旅游
保存：
{
"user":"张三",
"memory":[
"喜欢旅游",
"计划去上海"
]
}
下一次：
张三：
最近怎么样
机器人：
还不错，你不是准备下个月去上海玩吗？
推荐数据库设计
user表
id
微信昵称
备注
生日
兴趣
性格
message表
保存聊天：
用户
时间
内容
群
memory表
userid
内容
importance
embedding
大模型调用
建议不要绑定一个模型。
做一个LLM Gateway。
例如：
llm/
openai.py
claude.py
qwen.py
配置：
llm:
provider: openai
model:gpt-5
api_key:
以后切换：
GPT
|
Claude
|
DeepSeek
|
通义
不用改业务代码。
后台管理
建议做一个简单 Web 后台：
FastAPI + Vue
功能：
机器人设置
名字:
小龙虾
性格:
幽默
年龄:
30
定时任务
08:00 早安
22:30 晚安
生日提醒
群管理
群1:
开启机器人
群2:
关闭
模型配置
模型:
GPT-5
temperature:
0.8
max token:
1000