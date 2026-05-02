#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原神旅行札记账单抓取与报告生成工具
- 支持多角色，运行时交互选择需要监控的角色（或全部）
- 自动抓取最近三个月数据（无需询问）
- 每个角色单独一个目录存放数据与报告，以 UID 命名
- 合并所有本地历史数据，生成完整 Markdown 报告至 ./reports/{uid}/
- 分类汇总按原石数量降序排列
- 全局汇总：./reports/README.md 按服务器分组列出所有账号的游戏名、UID、总原石量
"""

import requests
import urllib.parse
import time
import json
import os
import sys
from datetime import datetime
from collections import defaultdict

# -------------------- 配置 --------------------
COOKIE_FILE = "./cookie.txt"
DEFAULT_GAME_BIZ = "hk4e_cn"
DATA_ROOT = "./data"
REPORT_ROOT = "./reports"

# -------------------- 工具函数 --------------------
def load_cookie():
    """从文件读取 Cookie，返回字典"""
    cookie = {}
    with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        if not content:
            raise ValueError("Cookie 文件为空")
        for item in content.split(';'):
            item = item.strip()
            if not item:
                continue
            item = urllib.parse.unquote(item)
            if '=' in item:
                key, value = item.split('=', 1)
                cookie[key.strip()] = value.strip()
    print(f"✅ Cookie 加载成功，包含 {len(cookie)} 个字段")
    return cookie

def get_user_roles(cookie, game_biz=DEFAULT_GAME_BIZ):
    """获取用户绑定的所有原神角色"""
    url = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    params = {'game_biz': game_biz}
    try:
        resp = requests.get(url, cookies=cookie, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        js = resp.json()
        if js.get('retcode') != 0:
            print(f"❌ 获取角色列表失败：{js.get('message', '未知错误')}")
            return []
        data = js.get('data', {})
        all_roles = data.get('list', [])
        genshin_roles = [r for r in all_roles if r.get('game_biz') == DEFAULT_GAME_BIZ]
        return genshin_roles
    except Exception as e:
        print(f"❌ 请求角色列表接口出错：{e}")
        return []

def select_role(roles):
    """交互式选择角色，返回 (uid, region, nickname, region_name) 或特殊标记 ('ALL', None, None, None)"""
    if not roles:
        print("❌ 当前 Cookie 下没有绑定任何原神角色，请检查 Cookie 或游戏绑定情况。")
        return None, None, None, None

    print("\n🎮 找到以下原神角色：")
    print("0. 或 all  -> 抓取以下全部角色")
    for idx, r in enumerate(roles):
        print(f"{idx + 1}. {r['nickname']} (UID: {r['game_uid']}) - {r['region_name']}")

    while True:
        choice = input("\n请选择角色（输入序号、UID 或 all）：").strip().lower()
        if choice in ('0', 'all'):
            return 'ALL', None, None, None
        if choice.isdigit() and 1 <= int(choice) <= len(roles):
            selected = roles[int(choice) - 1]
            return selected['game_uid'], selected['region'], selected['nickname'], selected['region_name']
        for r in roles:
            if r['game_uid'] == choice:
                return r['game_uid'], r['region'], r['nickname'], r['region_name']
        print("❌ 无效选择，请重新输入。")

def fetch_month(year, month, cookie, uid, region):
    """抓取指定年月的账单记录，返回记录列表"""
    records = []
    page = 1
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    while True:
        url = (
            f'https://act-hk4e-api.mihoyo.com/event/ys_ledger/monthDetail'
            f'?page={page}&month={month}&year={year}&limit=100&type=1'
            f'&bind_uid={uid}&bind_region={region}'
            f'&bbs_presentation_style=fullscreen&bbs_auth_required=true'
            f'&utm_source=bbs&utm_medium=mys&utm_campaign=icon'
        )
        try:
            resp = requests.get(url, cookies=cookie, headers=headers, timeout=10)
            resp.raise_for_status()
            js = resp.json()
            if js.get('retcode') != 0:
                print(f"⚠️ API 返回错误：{js.get('message', '未知错误')}")
                break
            data = js.get('data')
            if not data:
                break
            lis = data.get('list', [])
            if not lis:
                break
            for item in lis:
                records.append({
                    'time': item['time'],
                    'action': item['action'],
                    'num': int(item['num'])
                })
            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ 抓取 {year}-{month:02d} 第 {page} 页失败：{e}")
            break
    print(f"   📦 {year}-{month:02d} 获取到 {len(records)} 条记录")
    return records

def save_month_data(uid, year, month, records):
    """保存原始数据到 JSON 文件"""
    role_data_dir = os.path.join(DATA_ROOT, uid)
    os.makedirs(role_data_dir, exist_ok=True)
    filename = os.path.join(role_data_dir, f"{year}-{month:02d}.json")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"   💾 数据已保存至 {filename}")

def save_role_meta(uid, nickname, region, region_name):
    """保存角色元数据到 meta.json"""
    role_data_dir = os.path.join(DATA_ROOT, uid)
    os.makedirs(role_data_dir, exist_ok=True)
    meta_path = os.path.join(role_data_dir, "meta.json")
    meta = {
        "uid": uid,
        "nickname": nickname,
        "region": region,
        "region_name": region_name
    }
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

def load_role_meta(uid):
    """从 meta.json 读取角色元数据，返回 (nickname, region_name)；若不存在则返回 (uid, "未知服务器")"""
    meta_path = os.path.join(DATA_ROOT, uid, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                return meta.get("nickname", uid), meta.get("region_name", "未知服务器")
        except:
            pass
    return uid, "未知服务器"

def load_all_historical_data(uid):
    """读取该 UID 下所有历史 JSON 文件"""
    all_data = {}
    role_data_dir = os.path.join(DATA_ROOT, uid)
    if not os.path.exists(role_data_dir):
        return all_data
    for fname in os.listdir(role_data_dir):
        if not fname.endswith('.json') or fname == 'meta.json':
            continue
        try:
            year, month = map(int, fname.replace('.json', '').split('-'))
            with open(os.path.join(role_data_dir, fname), 'r', encoding='utf-8') as f:
                records = json.load(f)
            all_data[(year, month)] = records
            print(f"📂 加载历史数据：{year}-{month:02d} ({len(records)} 条)")
        except Exception as e:
            print(f"⚠️ 读取文件 {fname} 出错：{e}")
    return all_data

def process_data_into_summary(all_data):
    """将原始记录字典转换为汇总结构"""
    months_data = []
    for (year, month), records in sorted(all_data.items()):
        if not records:
            continue
        records.sort(key=lambda x: x['time'])
        daily = defaultdict(list)
        for r in records:
            date_str = r['time'][:10]
            daily[date_str].append(r)

        daily_summary = {}
        month_total = defaultdict(int)

        for date, recs in daily.items():
            date_total = defaultdict(int)
            for r in recs:
                date_total[r['action']] += r['num']
                date_total['total'] += r['num']
                month_total[r['action']] += r['num']
            month_total['total'] += date_total['total']
            daily_summary[date] = {
                'records': recs,
                'summary': date_total
            }

        months_data.append({
            'year': year,
            'month': month,
            'daily_summary': daily_summary,
            'month_total': month_total
        })
    return months_data

def generate_reports(uid, nickname, months_data):
    """生成该 UID 角色的完整 Markdown 报告到 reports/{uid}/ 目录"""
    role_report_dir = os.path.join(REPORT_ROOT, uid)
    os.makedirs(role_report_dir, exist_ok=True)
    root_readme_path = os.path.join(role_report_dir, 'README.md')

    with open(root_readme_path, 'w', encoding='utf-8') as root_readme:
        root_readme.write(f"# 原神旅行札记账单汇总\n\n ### {nickname} (UID: {uid}) \n\n")
        root_readme.write("| 月份 | 总原石 | 链接 |\n")
        root_readme.write("|------|--------|------|\n")

        global_total = defaultdict(int)

        for md in months_data:
            year = md['year']
            month = md['month']
            month_total_val = md['month_total']['total']
            month_folder = f"{year}-{month:02d}"

            for act, val in md['month_total'].items():
                global_total[act] += val

            root_readme.write(f"| {year}年{month:02d}月 | {month_total_val} | [查看](./{month_folder}/README.md) |\n")

            month_path = os.path.join(role_report_dir, month_folder)
            os.makedirs(month_path, exist_ok=True)

            # 生成月份 README
            month_readme_path = os.path.join(month_path, 'README.md')
            with open(month_readme_path, 'w', encoding='utf-8') as month_readme:
                month_readme.write(f"# {year}年{month:02d}月 原神账单\n\n ### {nickname} (UID: {uid}) \n\n")
                month_readme.write("| 日期 | 原石数 | 链接 |\n")
                month_readme.write("|------|--------|------|\n")

                sorted_dates = sorted(md['daily_summary'].keys())
                for date in sorted_dates:
                    daily_total = md['daily_summary'][date]['summary']['total']
                    date_filename = date.replace('-', '')
                    month_readme.write(f"| {date} | {daily_total} | [明细](./{date_filename}.md) |\n")

                month_readme.write(f"\n## 📊 月份总计\n\n")
                sorted_month_actions = sorted(
                    ((act, val) for act, val in md['month_total'].items() if act != 'total'),
                    key=lambda x: x[1],
                    reverse=True
                )
                for act, val in sorted_month_actions:
                    percent = (val / month_total_val) * 100 if month_total_val else 0
                    month_readme.write(f"- **{act}**：{val} ({percent:.2f}%)\n")
                month_readme.write(f"\n**🔥 总原石：{month_total_val}**\n")

                # 生成每日明细文件
                for date in sorted_dates:
                    info = md['daily_summary'][date]
                    date_filename = date.replace('-', '')
                    day_file_path = os.path.join(month_path, f'{date_filename}.md')
                    daily_total = info['summary']['total']

                    with open(day_file_path, 'w', encoding='utf-8') as day_file:
                        day_file.write(f"# {date} 原神账单明细\n\n ### {nickname} (UID: {uid}) \n\n")
                        day_file.write(f"当日总计：**{daily_total}** 原石\n\n")
                        day_file.write('<details open>\n')
                        day_file.write('<summary>📋 原石记录明细</summary>\n\n')
                        day_file.write("| 时间 | 动作 | 数量 |\n")
                        day_file.write("|------|------|------|\n")
                        for r in info['records']:
                            day_file.write(f"| {r['time']} | {r['action']} | {r['num']} |\n")
                        day_file.write('\n</details>\n\n')
                        day_file.write(f"\n## 📌 分类汇总\n\n")
                        sorted_day_actions = sorted(
                            ((act, val) for act, val in info['summary'].items() if act != 'total'),
                            key=lambda x: x[1],
                            reverse=True
                        )
                        for act, val in sorted_day_actions:
                            percent = (val / daily_total) * 100 if daily_total else 0
                            day_file.write(f"- **{act}**：{val} ({percent:.2f}%)\n")

        # 全局总计（当前角色）
        root_readme.write("\n## 🌍 全局总计\n\n")
        global_total_val = global_total['total']
        sorted_global_actions = sorted(
            ((act, val) for act, val in global_total.items() if act != 'total'),
            key=lambda x: x[1],
            reverse=True
        )
        for act, val in sorted_global_actions:
            percent = (val / global_total_val) * 100 if global_total_val else 0
            root_readme.write(f"- **{act}**：{val} ({percent:.2f}%)\n")
        root_readme.write(f"\n**🏆 历史总原石：{global_total_val}**\n")

    print(f"\n✅ 报告已生成于：{os.path.abspath(role_report_dir)}")

def compute_all_uids_total(data_root):
    """
    扫描 data_root 下所有 UID 子目录，汇总每个 UID 的总原石数量，并读取元数据
    返回列表，每个元素为 (uid, total, nickname, region_name)
    """
    result = []
    if not os.path.exists(data_root):
        return result

    for item in os.listdir(data_root):
        uid_dir = os.path.join(data_root, item)
        if not os.path.isdir(uid_dir):
            continue
        total = 0
        has_json = False
        for fname in os.listdir(uid_dir):
            if not fname.endswith('.json') or fname == 'meta.json':
                continue
            has_json = True
            filepath = os.path.join(uid_dir, fname)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    records = json.load(f)
                    for rec in records:
                        total += rec.get('num', 0)
            except Exception as e:
                print(f"⚠️ 读取文件 {filepath} 出错：{e}")
        if has_json:
            nickname, region_name = load_role_meta(item)
            result.append((item, total, nickname, region_name))
    return result

def generate_global_summary(accounts_info, report_root):
    """
    生成全局汇总报告 ./reports/README.md
    accounts_info: 列表，每个元素 (uid, total_primogems, nickname, region_name)
    按服务器分组，每组内按 UID 数值升序排序
    """
    os.makedirs(report_root, exist_ok=True)
    global_readme = os.path.join(report_root, 'README.md')

    if not accounts_info:
        with open(global_readme, 'w', encoding='utf-8') as f:
            f.write("# 原神旅行札记 · 全局账号汇总\n\n")
            f.write("目前没有任何账号数据，请先运行脚本抓取数据。\n")
        print("⚠️ 没有找到任何账号数据，全局汇总报告仅生成提示信息。")
        return

    # 按服务器分组
    groups = defaultdict(list)
    for uid, total, nickname, region_name in accounts_info:
        groups[region_name].append((uid, total, nickname))

    with open(global_readme, 'w', encoding='utf-8') as f:
        f.write("# 原神旅行札记 · 全局账号汇总\n\n")
        for region_name in sorted(groups.keys()):
            f.write(f"## 🌍 {region_name}\n\n")
            f.write("| 游戏名 | UID | 总原石量 | 详细报告 |\n")
            f.write("|:------:|:---:|:--------:|:--------:|\n")
            # 组内按 UID 数值升序排序
            for uid, total, nickname in sorted(groups[region_name], key=lambda x: int(x[0])):
                f.write(f"| {nickname} | {uid} | {total} | [查看](./{uid}/README.md) |\n")
            f.write("\n")

        grand_total = sum(total for _, total, _, _ in accounts_info)
        # f.write(f"\n**🌟 所有账号累计原石：{grand_total}**\n")

    print(f"\n✅ 全局汇总报告已生成：{os.path.abspath(global_readme)}")

def process_one_role(uid, region, nickname, region_name, cookie, fetch_new=True):
    """处理单个角色：抓取新数据（默认开启），加载历史并生成报告"""
    print(f"\n{'='*40}")
    print(f"🎮 正在处理角色 {nickname}（UID：{uid}） 服务器 {region_name}")
    print(f"{'='*40}")

    # 保存元数据
    save_role_meta(uid, nickname, region, region_name)

    if fetch_new:
        # 抓取最近三个月数据
        today = datetime.now()
        cur_year, cur_month = today.year, today.month
        months_to_fetch = []
        for offset in (2, 1, 0):
            y = cur_year
            m = cur_month - offset
            if m <= 0:
                m += 12
                y -= 1
            months_to_fetch.append((y, m))

        print(f"\n📅 即将抓取月份：{', '.join(f'{y}-{m:02d}' for y, m in months_to_fetch)}")

        for year, month in months_to_fetch:
            print(f"\n🔍 正在抓取 {year}-{month:02d} ...")
            records = fetch_month(year, month, cookie, uid, region)
            if records:
                save_month_data(uid, year, month, records)
            else:
                print(f"   ⚠️ {year}-{month:02d} 无数据，跳过保存")
    else:
        print("\n⏭️ 跳过网络抓取，仅使用本地数据。")

    # 加载该角色的所有历史数据
    print("\n📚 加载本地历史数据...")
    all_data = load_all_historical_data(uid)
    if not all_data:
        print("❌ 没有任何数据（本地无 JSON 文件），无法生成报告。")
        return False

    # 处理汇总数据
    print("\n🔄 处理数据...")
    months_data = process_data_into_summary(all_data)

    # 生成当前角色的 Markdown 报告
    print("\n📝 生成报告...")
    generate_reports(uid, nickname, months_data)

    return True

# -------------------- 主流程 --------------------
def main():
    print("=" * 50)
    print("原神旅行札记 · 历史账单归档工具")
    print("=" * 50)

    try:
        # 1. 加载 Cookie
        try:
            cookie = load_cookie()
        except Exception as e:
            print(f"❌ Cookie 加载失败：{e}")
            return

        # 2. 获取角色列表
        roles = get_user_roles(cookie)
        if not roles:
            print("未获取到任何原神角色，程序退出。")
            return

        # 3. 用户选择角色（或全部）
        selected_uid, selected_region, selected_nickname, selected_region_name = select_role(roles)
        if selected_uid is None and selected_region is None and selected_nickname is None and selected_region_name is None:
            return

        # 4. 自动抓取新数据（不再询问）
        fetch_new = True

        if selected_uid == 'ALL':
            print(f"\n🌟 选择全部角色，共 {len(roles)} 个，开始处理...")
            for r in roles:
                uid = r['game_uid']
                region = r['region']
                nickname = r['nickname']
                region_name = r['region_name']
                process_one_role(uid, region, nickname, region_name, cookie, fetch_new)
                # 角色之间稍作延迟，避免请求过快
                if fetch_new:
                    time.sleep(2)
        else:
            process_one_role(selected_uid, selected_region, selected_nickname, selected_region_name, cookie, fetch_new)

        # 5. 生成全局汇总报告（扫描所有 UID 数据）
        print("\n🌐 生成全局账号汇总报告...")
        accounts_info = compute_all_uids_total(DATA_ROOT)
        generate_global_summary(accounts_info, REPORT_ROOT)

        print("\n🎉 全部完成！")

    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断操作，程序已安全退出。")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 发生未预期的错误：{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()