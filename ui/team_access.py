"""Optional team gate; cloud deployments must explicitly configure access."""
import hashlib
import hmac
import os


def check_password(supplied: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8'))


def require_team_access(st):
    expected = os.getenv('RADAR_TEAM_PASSWORD', '')
    required = os.getenv('RADAR_REQUIRE_LOGIN', '').lower() in {'1', 'true', 'yes'}
    if not expected:
        if required:
            st.error('团队测试入口尚未配置访问口令，请管理员在托管平台设置 RADAR_TEAM_PASSWORD。')
            st.stop()
        return
    fingerprint = hashlib.sha256(expected.encode('utf-8')).hexdigest()
    if st.session_state.get('_radar_authenticated') == fingerprint:
        return
    st.title('招标雷达 · 团队测试')
    st.caption('输入团队访问口令，进入搜索、筛选和评分工作台。')
    with st.form('team_login'):
        supplied = st.text_input('团队访问口令', type='password')
        submitted = st.form_submit_button('进入工作台')
    if submitted:
        if check_password(supplied, expected):
            st.session_state['_radar_authenticated'] = fingerprint
            st.rerun()
        st.error('访问口令不正确。')
    st.stop()
