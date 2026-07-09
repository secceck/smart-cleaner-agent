"""
用户地理位置获取
浏览器只拿 GPS 坐标，城市反查和 IP 定位全部由后端完成
Geolocation API -> 后端反查 -> 后端 IP 定位 -> 手动输入四级降级
"""
import streamlit as st


def get_location_script(thread_id: str, api_base: str) -> str:
    """
    生成用于获取浏览器 GPS 坐标并上报到后端的 JavaScript 代码。
    城市名反查和 IP 定位由后端完成（服务端无 CORS/墙限制）。
    """
    return f"""
    <script>
    (async function() {{
        console.log('[Location] 开始获取 GPS 坐标... thread_id={thread_id}');

        // 获取 GPS 坐标（不再调用外部 API）
        var coords = await new Promise(function(resolve) {{
            if (!navigator.geolocation) {{
                console.log('[Location] 浏览器不支持 Geolocation API');
                resolve(null);
                return;
            }}
            navigator.geolocation.getCurrentPosition(
                function(pos) {{
                    console.log('[Location] GPS 坐标获取成功: lat=' + pos.coords.latitude + ' lng=' + pos.coords.longitude);
                    resolve({{ lat: pos.coords.latitude, lng: pos.coords.longitude }});
                }},
                function(err) {{
                    console.log('[Location] GPS 未授权或失败: code=' + err.code + ' msg=' + err.message);
                    resolve(null);
                }},
                {{ timeout: 8000, maximumAge: 600000, enableHighAccuracy: false }}
            );
        }});

        // 上报坐标到后端（由后端完成城市反查）
        var lat = coords ? coords.lat : 0;
        var lng = coords ? coords.lng : 0;
        try {{
            var postResp = await fetch('{api_base}/location', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    thread_id: '{thread_id}',
                    city: '',    // 由后端反查填充
                    lat: lat,
                    lng: lng
                }})
            }});
            if (postResp.ok) {{
                var result = await postResp.json();
                console.log('[Location] ✅ 后端返回城市: ' + (result.city || '(未识别)'));
                // 通知 Streamlit 刷新页面以读取最新位置（只刷新一次）
                try {{
                    if (!sessionStorage.getItem('_loc_reported')) {{
                        sessionStorage.setItem('_loc_reported', '1');
                        console.log('[Location] 即将刷新页面以应用位置...');
                        setTimeout(function() {{
                            window.top.location.reload();
                        }}, 500);
                    }}
                }} catch (e) {{
                    // sessionStorage 不可用（隐私模式），跳过自动刷新
                    // 位置将在下次用户交互时通过 st.rerun() 自动生效
                    console.log('[Location] sessionStorage 不可用，跳过自动刷新（位置将在下次交互时生效）');
                }}
            }} else {{
                console.log('[Location] ❌ 后端返回错误: HTTP ' + postResp.status);
            }}
        }} catch (e) {{
            console.log('[Location] ❌ 上报后端失败: ' + e.message);
        }}
    }})();
    </script>
    """


def inject_location_script(thread_id: str, api_base: str):
    """在 Streamlit 页面中注入位置获取脚本"""
    script = get_location_script(thread_id, api_base)
    # height=1 确保 iframe 被渲染并执行 JS（height=0 在某些 Streamlit 版本中不渲染）
    st.components.v1.html(script, height=1, scrolling=False)
