import streamlit as st
import time

st.set_page_config(page_title="Test")

if "msg" not in st.session_state:
    st.session_state.msg = "Hello World"

with st.chat_message("assistant"):
    st.markdown("Test message")

st.markdown("""
<script>
    setTimeout(function() {
        var html = document.body.innerHTML;
        // Send html back to a file or something, but Streamlit can't easily do this.
    }, 1000);
</script>
""", unsafe_allow_html=True)
