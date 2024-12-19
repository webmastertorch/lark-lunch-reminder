import os
import time
import json
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

clock_ins = {}

APP_ID = os.environ.get("APP_ID", "YOUR_APP_ID")
APP_SECRET = os.environ.get("APP_SECRET", "YOUR_APP_SECRET")
HR_USER_ID = os.environ.get("HR_USER_ID", "HR_USER_ID")

# 新增：从环境变量中获取 user_access_token（请根据实际情况提供）
USER_ACCESS_TOKEN = os.environ.get("USER_ACCESS_TOKEN", "YOUR_USER_ACCESS_TOKEN")

BOT_ACCESS_TOKEN = None
TOKEN_EXPIRY = 0
TARGET_DEPT_ID = "od-d426edf9693be928abbec635cb290358"

def get_bot_access_token():
    global BOT_ACCESS_TOKEN, TOKEN_EXPIRY
    current_time = int(time.time())
    if BOT_ACCESS_TOKEN is not None and current_time < TOKEN_EXPIRY:
        return BOT_ACCESS_TOKEN

    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    data = resp.json()
    print("Token response:", data)
    BOT_ACCESS_TOKEN = data.get("tenant_access_token")
    if BOT_ACCESS_TOKEN:
        TOKEN_EXPIRY = current_time + 7000
    else:
        print("Failed to get tenant_access_token. Check APP_ID/APP_SECRET and permissions.")
    return BOT_ACCESS_TOKEN

def send_message(user_id, text):
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=user_id"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}",
        "Content-Type": "application/json"
    }
    safe_text = text.replace("（", "(").replace("）", ")")
    content_str = json.dumps({"text": safe_text})
    payload = {
        "receive_id": user_id,
        "msg_type": "text",
        "content": content_str
    }
    response = requests.post(url, headers=headers, json=payload)
    resp_data = response.json()
    print(f"Sending message to {user_id}: {resp_data}")
    return resp_data

def get_user_info_by_user_access_token():
    """
    使用 user_access_token 获取登录用户的信息
    根据你提供的接口说明：
    GET https://open.feishu.cn/connect/qrconnect/oauth2/user_info/
    Header:
        Authorization: Bearer <user_access_token>
    返回数据示例：
    {
        "AvatarUrl":"https://open.feishu.cn/avatar/zhangsan",
        "Name": "zhangsan",
        "Email": "zhangsan@gmail.com",
        "Status": 0,
        "EmployeeID":"5d9bdxx",
        "Mobile":"+86130xxx"
    }
    """
    url = "https://open.feishu.cn/connect/qrconnect/oauth2/user_info/"
    headers = {
        "Authorization": f"Bearer {USER_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    resp = requests.get(url, headers=headers)
    data = resp.json()
    return data

def get_user_name():
    """
    使用上面的接口获取用户信息，从中提取 Name 字段作为用户名
    """
    user_data = get_user_info_by_user_access_token()
    # 假设正常返回并有 Name 字段
    return user_data.get("Name", "未知用户")

def check_user_department(user_id):
    """
    原本的部门检查逻辑，如需保留请根据实际情况实现。
    此处为占位符，假定始终返回 True。
    实际使用中如果需要根据employee_id或其他信息判断部门，需要调用相应接口。
    """
    # TODO: 实现部门判断逻辑
    # 由于本次主要关注获取用户名，这里简单返回True
    return True

def check_and_notify(user_id, clock_in_time):
    print(f"Check started for {user_id}, time: {clock_in_time}")
    time.sleep(10)  # 测试环境下10秒，正式使用5小时
    if user_id in clock_ins:
        print(f"User {user_id} still not off-duty, checking department before sending reminder...")
        if check_user_department(user_id):
            print(f"User {user_id} is in target department {TARGET_DEPT_ID}, sending reminder...")
            user_name = get_user_name()  # 使用user_access_token获取用户名
            send_message(user_id, "您已经连续工作5小时，请尽快休息并下班打卡(如果需要)。")
            send_message(HR_USER_ID, f"员工 {user_name} 已连续5小时未下班。")
        else:
            print(f"User {user_id} is not in department {TARGET_DEPT_ID}, no message sent.")
    else:
        print(f"User {user_id} is off-duty now, no reminder needed.")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Received event:", data)

    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    header = data.get("header", {})
    event = data.get("event", {})

    create_time_ms = header.get("create_time", 0)
    punch_time = int(create_time_ms) / 1000.0 if create_time_ms else time.time()

    user_id = event.get("employee_id")
    status_changes = event.get("status_changes", [])

    index_map = {}
    for change in status_changes:
        idx = change.get("index")
        work_type = change.get("work_type")
        current_status = change.get("current_status", "")
        print(f"Found work_type={work_type}, current_status={current_status} for user {user_id} at index={idx}")
        if idx not in index_map:
            index_map[idx] = []
        index_map[idx].append((work_type, current_status))

    if not index_map:
        print(f"User {user_id} no index data, no action.")
        return jsonify({"code": 0, "msg": "success"})

    max_index = max(index_map.keys())
    records = index_map[max_index]

    if len(records) == 2:
        first = records[0]  # (on, Normal)
        second = records[1] # (off, '' or Normal)
        if first[0] == "on" and first[1] == "Normal":
            if second[0] == "off":
                if second[1] == "":
                    # 实为clock in
                    clock_ins[user_id] = punch_time
                    print(f"User {user_id} is actually clock in at index={max_index}, starting check thread.")
                    t = threading.Thread(target=check_and_notify, args=(user_id, punch_time))
                    t.start()
                elif second[1] == "Normal":
                    # 实为clock out
                    if user_id in clock_ins:
                        del clock_ins[user_id]
                        print(f"User {user_id} is actually clock out at index={max_index}, removed from clock_ins.")
                    else:
                        print(f"User {user_id} is actually clock out at index={max_index}, but not in clock_ins.")
                else:
                    print(f"User {user_id} at index={max_index}, off status unexpected: {second[1]}")
            else:
                print(f"User {user_id} at index={max_index}, second record not off: {second}")
        else:
            print(f"User {user_id} at index={max_index}, first record not (on, Normal): {first}")
    else:
        print(f"User {user_id} at index={max_index} has unexpected record count: {len(records)}")

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Starting app on port:", port)
    app.run(host="0.0.0.0", port=port)
