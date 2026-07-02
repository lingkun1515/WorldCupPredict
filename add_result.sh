#!/bin/bash
# ═══════════════════════════════════════════════════
# 手动添加赛果: ./add_result.sh "法国" "瑞典" 3 1
# 自动重建页面
# ═══════════════════════════════════════════════════
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ $# -lt 4 ]; then
    echo "用法: ./add_result.sh <主队> <客队> <主队进球> <客队进球>"
    echo "示例: ./add_result.sh 法国 瑞典 3 1"
    exit 1
fi

HOME_TEAM="$1"
AWAY_TEAM="$2"
HOME_GOALS="$3"
AWAY_GOALS="$4"
DATE="$(date +%Y-%m-%d)"

cd "$DIR"
python3 -c "
import json, sys
home='$HOME_TEAM'; away='$AWAY_TEAM'
hg=int('$HOME_GOALS'); ag=int('$AWAY_GOALS')

# Load existing results
results=[]
try:
    with open('data/results.json') as f:
        results=json.load(f)
except: pass

# Remove old entry for this match
results=[r for r in results if not (
    (r['home']==home and r['away']==away) or 
    (r['home']==away and r['away']==home)
)]

# Add new result
results.append({
    'home':home,'away':away,
    'home_goals':hg,'away_goals':ag,
    'date':'$DATE','stage':'32强淘汰赛'
})

with open('data/results.json','w') as f:
    json.dump(results,f,indent=2,ensure_ascii=False)

# Update matches.json
with open('data/matches.json') as f:
    matches=json.load(f)
for m in matches:
    if m['home_team']==home and m['away_team']==away:
        m['completed']=True
        m['home_goals']=hg
        m['away_goals']=ag
with open('data/matches.json','w') as f:
    json.dump(matches,f,indent=2,ensure_ascii=False)

print(f'✓ 已添加: {home} {hg}-{ag} {away}')
print(f'  共 {len(results)} 条赛果')
"

# Rebuild
python3 build_static.py 2>&1 | tail -1
echo "✓ 页面已更新，浏览器刷新即可"
