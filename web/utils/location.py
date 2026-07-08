"""
用户地理位置获取
通过浏览器 JS 获取定位，直接调用后端 API 写入缓存
Geolocation API -> IP 定位 -> 手动输入三级降级
"""
import streamlit as st


def get_location_script(thread_id: str, api_base: str) -> str:
    """
    生成用于获取浏览器地理位置并上报到后端的 JavaScript 代码
    """
    return f"""
    <script>
    async function getUserLocation() {{
        var city = null;

        // 1. 尝试浏览器 Geolocation API
        try {{
            city = await new Promise(function(resolve) {{
                if (!navigator.geolocation) {{
                    resolve(null);
                    return;
                }}
                navigator.geolocation.getCurrentPosition(
                    async function(pos) {{
                        try {{
                            var lat = pos.coords.latitude;
                            var lng = pos.coords.longitude;
                            var resp = await fetch(
                                'https://nominatim.openstreetmap.org/reverse?lat=' + lat + '&lon=' + lng + '&format=json&accept-language=zh'
                            );
                            var data = await resp.json();
                            var c = data.address ? (data.address.city || data.address.town || data.address.county || data.address.state || null) : null;
                            resolve(c);
                        }} catch (e) {{
                            resolve(null);
                        }}
                    }},
                    function() {{ resolve(null); }},
                    {{ timeout: 5000, maximumAge: 600000 }}
                );
            }});
        }} catch (e) {{}}

        // 2. IP 定位降级
        if (!city) {{
            try {{
                var resp = await fetch('https://ipapi.co/json/');
                var data = await resp.json();
                city = data.city || null;
            }} catch (e) {{}}
        }}

        // 3. 上报到后端
        if (city) {{
            try {{
                await fetch('{api_base}/location', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{thread_id: '{thread_id}', city: city}})
                }});
                console.log('Location sent to backend: ' + city);
            }} catch (e) {{
                console.log('Failed to send location: ' + e);
            }}
        }} else {{
            console.log('Could not determine location');
        }}
    }}
    getUserLocation();
    </script>
    """


def inject_location_script(thread_id: str, api_base: str):
    """在 Streamlit 页面中注入位置获取脚本"""
    script = get_location_script(thread_id, api_base)
    st.components.v1.html(script, height=0)
