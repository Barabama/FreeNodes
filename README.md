# FreeNodes

v2ray 免费节点


## 免责声明

订阅节点仅作学习交流使用，用于查找资料，学习知识，不做任何违法行为。所有资源均来自互联网，仅供大家交流学习使用，出现违法问题概不负责。

## api请求鸣谢

- 字幕提取密码OCR: https://cloud.baidu.com/doc/OCR/index.html
- 地理位置查询: https://ip-api.com/

## 配置文件

```json5
// config.json
{
  "name": {
    "name": "name", // 名字
    "tier": 0,      // 梯级为1的会被合并
    "up_date": "2024-01-01", // 更新日期
    "main_url": "https://",  // 目标主页
    "attrs": {"rel": "bookmark"},       // 用于匹配详情页链接元素
    "pattern": "http://[^<>\\n]+.txt",  // 节点链接匹配规则
    "nodes_index": 0, // 节点链接索引
    "decryption": {   // 需要解密时使用
      "yt_index": 0,  // 油管视频链接索引
      "decrypt_by": "js",  // 解密方法, "js"脚本触发或"click"模拟点击
      "script": "multiDecrypt(arguments[0]);", // 仅"js", 脚本名
      "textbox": ["id","textbox"],  // 仅"click", 匹配密码文本框
      "button": ["name","Submit"],  // 仅"click", 匹配提交密码按钮
      "password": "8888"  // 上次成功解密密码
    }
  }
}
```
