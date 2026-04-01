# monitor

## 配置 Actions

• 仓库设置：进入 Settings -> Actions -> General。
• Workflow permissions：滚动到底部，确保选中了 Read and write permissions。
• 允许提交：勾选下方出现的 Allow GitHub Actions to create and approve pull requests（视情况而定，但读写权限是必须的）。

## 配置 variables

• 进入你的 GitHub 仓库，点击 Settings -> Secrets and variables -> Actions。
• 点击 New repository secret，添加以下变量（变量名: webhook）：
• 
FEISHU_RSS_HOOK : 填入一个飞书webhook
FEISHU_HOOK_WEBPAGE  : 填入一个飞书webhook

### 本地运行

将链接替换为你的

```bash
$env:FEISHU_HOOK_RSS="https://open...."
$env:FEISHU_HOOK_WEBPAGE="https://open...."
```


#### 运行

本地开始运行

```bash
python monitor.py
```

#### 本地环境安装


```bash
#创建虚拟环境: 
python -m venv venv
##### macOS专用
python3 -m venv venv

#激活虚拟环境: 
#(Windows) 
venv\Scripts\activate 
#(Linux/Mac)专用
source venv/bin/activate 



# pip

## 安装导出的依赖
pip install -r requirements.txt

## 升级pip
python.exe -m pip install --upgrade pip

### 创建 requirements.txt
pip freeze > requirements.txt

### 查看内容并手动填充到requirements.txt
pip freeze

### 查看已安装（虚拟环境和非虚拟环境有所区别）
pip list
#### macOS专用
pip3 list


```

