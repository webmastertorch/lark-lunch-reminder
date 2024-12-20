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

BOT_ACCESS_TOKEN = None
TOKEN_EXPIRY = 0

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

def get_user_name_by_employee_id(employee_id):
    """
    使用GET /open-apis/contact/v3/users接口，通过employee_id搜索用户。
    返回的数据中包含多个用户，用user_id精确匹配employee_id，以获取正确用户的名字。
    如果未找到匹配用户则返回None。
    """
    url = "https://open.larksuite.com/open-apis/contact/v3/users"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}"
    }
    params = {
        "employee_id": employee_id,
        "employee_id_type": "employee_id",
        "user_id_type": "user_id"
    }
    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()
    print("User list response:", data)

    if data.get("code") == 0:
        items = data.get("data", {}).get("items", [])
        # 遍历 items ，找出 user_id == employee_id 的用户
        for user in items:
            if user.get("user_id") == employee_id:
                return user.get("name") or None
    return None

def check_and_notify(employee_id, start_time):
    print(f"Check started for {employee_id}, time: {start_time}")
    # 等待4.5小时 (4.5 * 3600 = 16200 秒)
    time.sleep(16200)
    # 检查当前场景是否一致
    if employee_id in clock_ins:
        if clock_ins[employee_id] == start_time:
            # 在给员工发送提醒之前验证用户是否存在
            user_name = get_user_name_by_employee_id(employee_id)
            if user_name is not None:
                # 用户存在，发送给员工提醒(英文在前，中文在后)
                print(f"User {employee_id} not off-duty after 4.5 hours, reminding user...")
                employee_message = "You have been working for 4.5 hours continuously. Please take a break and clock out if necessary.\n您已经连续工作4.5小时，请尽快休息并下班打卡(如果需要)。"
                send_message(employee_id, employee_message)

                # 再等待0.5小时 (1800秒), 总计5小时
                time.sleep(1800)
                if employee_id in clock_ins and clock_ins[employee_id] == start_time:
                    # 再次检查用户是否存在
                    user_name = get_user_name_by_employee_id(employee_id)
                    if user_name is not None:
                        print(f"User {employee_id} not off-duty after 5 hours, reminding HR...")
                        hr_message = f"Employee {user_name} has not clocked out after 5 hours of continuous work."
                        send_message(HR_USER_ID, hr_message)
                    else:
                        print(f"User {employee_id} not found in user list response at 5h mark, no HR reminder.")
                else:
                    print(f"User {employee_id} off-duty within 0.5 hour after employee reminder or scenario changed, no HR reminder needed.")
            else:
                print(f"User {employee_id} not found in user list at 4.5h mark, no reminder to employee.")
        else:
            print(f"Scenario changed for user {employee_id}, no reminder needed.")
    else:
        print(f"User {employee_id} is off-duty or scenario changed before 4.5 hours, no reminders needed.")

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

    employee_id = event.get("employee_id")
    status_changes = event.get("status_changes", [])

    index_map = {}
    for change in status_changes:
        idx = change.get("index")
        work_type = change.get("work_type")
        current_status = change.get("current_status", "")
        print(f"Found work_type={work_type}, current_status={current_status} for user {employee_id} at index={idx}")
        if idx not in index_map:
            index_map[idx] = []
        index_map[idx].append((work_type, current_status))

    if not index_map:
        print(f"User {employee_id} no index data, no action.")
        return jsonify({"code": 0, "msg": "success"})

    max_index = max(index_map.keys())
    records = index_map[max_index]

    if len(records) == 2:
        first = records[0]  # (on, Normal)
        second = records[1] # (off, '' or Normal)
        if first[0] == "on" and first[1] == "Normal":
            # 确认为上班打卡场景
            if second[0] == "off":
                if second[1] == "":
                    # 上班打卡
                    clock_ins[employee_id] = punch_time
                    print(f"User {employee_id} is actually clock in at index={max_index}, starting check thread.")
                    # 将punch_time作为场景标识传入线程
                    t = threading.Thread(target=check_and_notify, args=(employee_id, punch_time))
                    t.start()
                elif second[1] == "Normal":
                    # 下班打卡
                    if employee_id in clock_ins:
                        del clock_ins[employee_id]
                        print(f"User {employee_id} is actually clock out at index={max_index}, removed from clock_ins.")
                    else:
                        print(f"User {employee_id} clock out but not in clock_ins, no action.")
                else:
                    print(f"User {employee_id} at index={max_index}, off status unexpected: {second[1]}")
            else:
                print(f"User {employee_id} at index={max_index}, second record not off: {second}")
        else:
            print(f"User {employee_id} at index={max_index}, first record not (on, Normal): {first}")
    else:
        print(f"User {employee_id} at index={max_index} has unexpected record count: {len(records)}")

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Starting app on port:", port)
    app.run(host="0.0.0.0", port=port)
