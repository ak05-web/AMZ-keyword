import streamlit as st


def check_password():
    """
    Returns True if the user has entered the correct password.
    Password is read from st.secrets['app_password'] (set in
    .streamlit/secrets.toml locally, or in Streamlit Cloud's
    'Secrets' settings when deployed). Never hardcode the password
    in code so the repo stays safe to keep public on GitHub.
    """

    def password_entered():
        entered = st.session_state.get("password_input", "")
        correct = st.secrets.get("app_password", None)
        if correct is None:
            st.session_state["auth_error"] = (
                "No password set. Add app_password to .streamlit/secrets.toml"
            )
            st.session_state["password_correct"] = False
            return
        if entered == correct:
            st.session_state["password_correct"] = True
            st.session_state.pop("password_input", None)
            st.session_state.pop("auth_error", None)
        else:
            st.session_state["password_correct"] = False
            st.session_state["auth_error"] = "Galat password, dobara try karo."

    if st.session_state.get("password_correct", False):
        return True

    st.title("🔒 Amazon Keyword & Competitor Tool")
    st.text_input(
        "Password",
        type="password",
        key="password_input",
        on_change=password_entered,
    )
    if st.session_state.get("auth_error"):
        st.error(st.session_state["auth_error"])
    st.caption("Personal-use tool. Password protected access only.")
    return False
