# app.py
import streamlit as st
import pandas as pd
import json
import altair as alt
import os
from datetime import datetime
import logging
import re # Keep re for name validation regex
import shutil # Added shutil for backup

# Import backend modules
from blockchain import MedicalBlockchain, BLOCKCHAIN_FILE # Assuming blockchain.py is in the same directory
from ai_module import MedicalAI
# This line imports the IPFSManager class from your ipfs.py file
from ipfs import IPFSManager

# ============ App Configuration ============
st.set_page_config(
    page_title="医疗数据管理系统 (模拟)",
    layout="wide",
    page_icon="🏥"
)

# ============ Logging Configuration ============\
# Ensure logs dir exists
LOGS_DIR = 'logs'
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, 'app.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        # logging.StreamHandler() # Optional: Uncomment to also log to console
    ]
)
logging.info("Application starting...")

# ============ Constants ============
ADMIN_PASSWORD = "admin123" # Replace with secure handling in production
SUPER_ADMIN_PASSWORD = "admin.123" # Replace with secure handling in production

# ============ Initialize Backend Components ============
# Use try-except block to handle initialization errors gracefully
# This is the section where the NameError occurs if IPFSManager is not imported
try:
    if 'ipfs_manager' not in st.session_state:
        st.session_state.ipfs_manager = IPFSManager(simulate=True) # Force simulation
        logging.info("IPFSManager initialized.")
    if 'analyzer' not in st.session_state:
        st.session_state.analyzer = MedicalAI()
        logging.info("MedicalAI analyzer initialized.")
    if 'blockchain' not in st.session_state:
        # Pass the initialized IPFS manager to the blockchain
        st.session_state.blockchain = MedicalBlockchain(st.session_state.ipfs_manager)
        logging.info("MedicalBlockchain initialized.")

    # Perform a quick health check (optional)
    # Example: Check if genesis block exists
    # if not st.session_state.blockchain.get_block(0): # get_block needs to be verified if it implies chain loading
    #      raise RuntimeError("Blockchain initialization failed: Genesis block not found.")

    st.session_state['initialized'] = True
    logging.info("Backend components initialized successfully.")

except Exception as e:
    logging.error(f"Fatal Error during backend initialization: {e}", exc_info=True)
    st.error(f"系统启动失败，请检查日志文件 {LOG_FILE}。错误: {e}")
    st.stop() # Stop execution if core components fail

# ============ Session State Initialization ============
# Initialize session state variables if they don't exist
default_session_state = {
    'logged_in': False,
    'is_admin': False,
    'is_super_admin': False,
    'current_user': None, # Store user identifier if needed
    'error_message': None,
    'success_message': None,
    'active_block_to_manage': None, # Initialize here for session state access in Tab 2 management form
    'query_results_df': None # Store query results DataFrame in session state
}
for key, default_value in default_session_state.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# ============ Utility Functions ============

def display_messages():
    """Displays success or error messages stored in session state and clears them after display."""
    # --- Modification: Restore clearing messages after display ---
    if st.session_state.success_message:
        st.success(st.session_state.success_message)
        st.session_state.success_message = None # Clear after displaying
    if st.session_state.error_message:
        st.error(st.session_state.error_message)
        st.session_state.error_message = None # Clear after displaying
    # --- End Modification ---


def validate_patient_name(name):
    """Validates patient name format using Regex (consistent with IPFSManager)."""
    if not isinstance(name, str):
        return False, "姓名必须是文本。"
    name = name.strip()
    # Allow Chinese characters, letters, spaces, hyphens, middle dots (·), periods (.), double quotes (")
    # Length between 2 and 50 characters
    if not (2 <= len(name) <= 50):
        return False, "姓名长度必须在 2 到 50 个字符之间。"
    # --- Modification: Use raw string to avoid SyntaxWarning ---
    # Ensure hyphen is escaped correctly if needed in the character set context
    if not re.fullmatch(r'^[\u4e00-\u9fa5a-zA-Z\s\-·.\"]+$', name, re.UNICODE):
    # --- End Modification ---
        return False, "姓名包含无效字符。只允许中文、字母、空格、连字符 (-)、点 (.)、中文中点 (·) 或英文双引号 (\")。"

    # Ensure it doesn't consist *only* of spaces/hyphens/dots/quotes
    # Using a raw string for robustness
    if re.fullmatch(r'^[ \-·.\"]+$', name): # Check if *all* chars are spaces/punctuation
         return False, "姓名不能只包含空格或标点符号。"
    # --- End Modification ---


    return True, ""


def check_duplicate_content(blockchain, ipfs_manager, patient_id, record_content):
    """Checks if identical record content already exists for the patient."""
    try:
        # Get active records for the patient view (efficiently checks current state)
        active_records_view = blockchain.get_chain_view(patient_id=patient_id, include_history=False)
        for block in active_records_view:
            try:
                # Retrieve data only if it's an ACTIVE CREATE or ACTIVE UPDATE block in the view
                 if block.get('transaction_type') in ['CREATE', 'UPDATE'] and block.get('current_status') == 'ACTIVE':
                     # Retrieve data using ipfs_manager
                     ipfs_hash = block.get('ipfs_hash')
                     encryption_key = block.get('metadata', {}).get('encryption_key')
                     if ipfs_hash and encryption_key:
                          # Need a way to get encryption key from the block metadata
                          data = ipfs_manager.retrieve_data(ipfs_hash, encryption_key)
                          # Compare only the 'record' content
                          if data and data.get('record') == record_content:
                              logging.warning(f"Duplicate content detected for patient {patient_id} in active block {block.get('block_id')}.")
                              return True # Duplicate found

            except ValueError as ve:
                 # Log decryption/retrieval errors for a specific block during check but continue
                 logging.error(f"Error retrieving data for block {block.get('block_id')} during duplicate check: {ve}", exc_info=False)
                 continue # Continue checking other blocks
            except Exception as e:
                 # Log other unexpected errors for a specific block during check but continue
                 logging.error(f"Unexpected error processing block {block.get('block_id')} during duplicate check: {e}", exc_info=False)
                 continue # Continue checking other blocks

        return False # No duplicate found among active records
    except Exception as e:
         logging.error(f"Error during overall duplicate content check for patient {patient_id}: {e}", exc_info=True)
         # Fail safe: assume not duplicate if the overall check process fails, but log error
         return False


def format_risk_display(risk_score):
    """Formats risk score with color."""
    try:
        # Ensure risk_score is treated as a number
        score = float(risk_score)
        if score > 0.7:
            return f"<span style='color: #cf222e; font-weight: bold;'>高风险 ({score*100:.0f}%)</span>"
        elif score > 0.4:
            return f"<span style='color: #9a6700;'>中风险 ({score*100:.0f}%)</span>"
        else:
            return f"<span style='color: #1a7f37;'>低风险 ({score*100:.0f}%)</span>"
    except (ValueError, TypeError):
        return "风险未知" # Handle cases where risk_score is not a valid number

def format_sensitivity_display(sensitivity_level):
     """Formats sensitivity level with styling."""
     # Ensure sensitivity_level is treated as a string and lowercase
     level = str(sensitivity_level).lower()
     if level == 'high':
          return "<div style='background-color: #ffebee; border-left: 4px solid #f44336; padding: 5px; margin: 2px 0;'>🔒 高敏感</div>"
     elif level == 'medium':
          return "<div style='background-color: #fff8e1; border-left: 4px solid #ffc107; padding: 5px; margin: 2px 0;'>⚠️ 中敏感</div>"
     else:
          return "<div style='background-color: #e8f5e9; border-left: 4px solid #1a7f37; padding: 5px; margin: 2px 0;'>✔️ 低敏感</div>"


def create_history_chart(df):
    """Creates a simple Altair bar chart for visit history."""
    # Check if DataFrame is valid and has required columns
    if df is None or df.empty or 'timestamp' not in df.columns or 'transaction_type' not in df.columns:
        return None
    try:
        # Convert timestamp to date for grouping
        df['date'] = pd.to_datetime(df['timestamp']).dt.date
        # Filter for transaction types that represent a visit
        chart_data = df[df['transaction_type'].isin(['CREATE', 'UPDATE'])]
        if chart_data.empty:
            return None

        # Create Altair chart
        chart = alt.Chart(chart_data).mark_bar().encode(
            x=alt.X('date:T', title='就诊日期', axis=alt.Axis(format="%Y-%m-%d")), # Format date on axis
            y=alt.Y('count()', title='就诊次数'), # Use count() for aggregation
            tooltip=[alt.Tooltip('date:T', title='日期', format="%Y-%m-%d"), alt.Tooltip('count()', title='次数')]
        ).properties(
            title='患者就诊历史统计 (仅限创建/更新记录)',
            height=300
        ).interactive() # Make chart interactive (zoom/pan)

        return chart
    except Exception as e:
        logging.error(f"Failed to create history chart: {e}", exc_info=True)
        return None


# ============ Styling ============
st.markdown("""
<style>
    /* Add custom styles here if needed */
    .stButton>button { margin-top: 10px; }
    .stSpinner { margin: 15px 0; }
</style>
""", unsafe_allow_html=True)


# ============ Login Screen ============
if not st.session_state.logged_in:
    st.title("🏥 医疗数据管理系统登录 (模拟)")
    # --- Modification: Ensure IPFS simulation mode is visible ---
    st.markdown('<div style="background-color: #fff3e0; color: #e65100; padding: 10px; border-radius: 5px; margin-bottom: 15px;">🟡 IPFS模拟模式 - 数据仅存储在本地</div>', unsafe_allow_html=True)
    # --- End Modification ---

    login_type = st.radio("选择登录类型:", ["普通用户", "管理员", "超级管理员"], key="login_type_radio")

    username = st.text_input("用户名 (可选，用于记录操作者)") # Added username input
    password = st.text_input("密码", type="password")

    if st.button("登录", key="login_button"):
        login_successful = False
        is_admin = False
        is_super_admin = False
        user = username.strip() if username else "anonymous"

        if login_type == "普通用户":
            # No password check for regular users in this example
            login_successful = True
            logging.info(f"User '{user}' logged in as 普通用户.")
        elif login_type == "管理员":
            if password == ADMIN_PASSWORD:
                login_successful = True
                is_admin = True
                logging.info(f"User '{user}' logged in as 管理员.")
            else:
                st.error("管理员密码错误！")
                logging.warning(f"Failed admin login attempt for user '{user}'.")
        elif login_type == "超级管理员":
            if password == SUPER_ADMIN_PASSWORD:
                login_successful = True
                is_admin = True # Super admin is also an admin
                is_super_admin = True
                logging.info(f"User '{user}' logged in as 超级管理员.")
            else:
                st.error("超级管理员密码错误！")
                logging.warning(f"Failed super admin login attempt for user '{user}'.")

        if login_successful:
            st.session_state.logged_in = True
            st.session_state.is_admin = is_admin
            st.session_state.is_super_admin = is_super_admin
            st.session_state.current_user = user
            # --- Modification: Clear messages on successful login ---
            st.session_state.success_message = None
            st.session_state.error_message = None
            # --- End Modification ---
            st.rerun() # Rerun to show the main app interface

    st.stop() # Stop execution here if not logged in

# ============ Main Application UI ============
st.title("🏥 医疗数据管理系统")

# Display system & login status
status_badge = '<div style="background-color: #fff3e0; color: #e65100; padding: 5px 10px; border-radius: 5px; display: inline-block; margin-right: 10px;">🟡 IPFS模拟模式</div>'
login_status = "👤 普通用户"
if st.session_state.is_super_admin:
    login_status = "🔑 超级管理员"
elif st.session_state.is_admin:
    login_status = "🔑 管理员"
login_status_badge = f'<div style="background-color: #e3f2fd; color: #0d47a1; padding: 5px 10px; border-radius: 5px; display: inline-block;">{login_status} ({st.session_state.current_user})</div>'

st.markdown(f"{status_badge} {login_status_badge}", unsafe_allow_html=True)
st.divider()

# Display messages (like success/error after actions)
# This function no longer clears messages, they persist until overwritten or explicitly cleared elsewhere
display_messages()

# Logout Button
if st.button("登出", key="logout_button"):
    user = st.session_state.current_user
    # Clear relevant session state on logout
    for key in default_session_state:
         # Keep initialized backend components, but clear other session state
         if key != 'initialized':
             st.session_state[key] = default_session_state[key]
    logging.info(f"User '{user}' logged out.")
    st.rerun()

# ============ Feature Tabs ============
tab1, tab2, tab3 = st.tabs(["📝 记录录入", "🔍 数据查询与管理", "⚙️ 系统管理"])

# --- Tab 1: Record Entry ---
with tab1:
    st.subheader("新增医疗记录")
    with st.form("record_form", clear_on_submit=True):
        patient_id = st.text_input("患者ID*", help="请输入患者唯一标识 (例如: 身份证号、医保卡号)")
        patient_name = st.text_input("患者姓名*", help="请输入患者真实姓名 (2-50字符)")
        medical_record_content = st.text_area("诊疗内容*", height=250, help="详细描述症状、检查结果、诊断和治疗方案等。")

        submitted = st.form_submit_button("提交记录")

        if submitted:
            valid_input = True
            error_msg = ""

            # Clear previous messages before new submission
            st.session_state.success_message = None
            st.session_state.error_message = None


            # Validate inputs
            if not patient_id.strip():
                valid_input = False
                error_msg += "患者ID不能为空。\n"
            valid_name, name_err = validate_patient_name(patient_name)
            if not valid_name:
                 valid_input = False
                 error_msg += f"{name_err}\n"
            if not medical_record_content.strip():
                valid_input = False
                error_msg += "诊疗内容不能为空。\n"

            if valid_input:
                # More checks before processing
                patient_id = patient_id.strip()
                patient_name = patient_name.strip()
                medical_record_content = medical_record_content.strip()

                # Check for patient name consistency (using blockchain's method)
                try:
                     # Pass ipfs_manager to check_duplicate_content
                     if not st.session_state.blockchain._verify_patient_name_consistency(patient_id, patient_name):
                          valid_input = False
                          error_msg += f"患者姓名与ID {patient_id} 的现有记录不符。\n"
                     # Check for duplicate content
                     elif check_duplicate_content(st.session_state.blockchain, st.session_state.ipfs_manager, patient_id, medical_record_content): # Pass ipfs_manager
                          valid_input = False
                          error_msg += "检测到该患者已存在完全相同的诊疗内容记录。\n"
                except Exception as check_err:
                     valid_input = False
                     error_msg += f"检查记录时出错: {check_err}\n"
                     logging.error(f"Error during pre-submission checks for patient {patient_id}: {check_err}", exc_info=True)


            if valid_input:
                with st.spinner("正在分析并存储记录..."):
                    try:
                        # 1. Analyze text using AI module
                        # Ensure analysis_result is handled correctly if AI module returns None or error structure
                        analysis_result = st.session_state.analyzer.analyze_text(medical_record_content, patient_name)
                        # Provide default empty values if analysis_result is None or missing keys
                        analysis_result = analysis_result if analysis_result else {}
                        diagnosis = analysis_result.get('diagnosis', [])
                        diagnosis_suggestions = analysis_result.get('diagnosis_suggestions', [])
                        treatment = analysis_result.get('treatment', [])
                        treatment_suggestions = analysis_result.get('treatment_suggestions', [])
                        symptoms = analysis_result.get('symptoms', [])
                        risk_score = analysis_result.get('risk_score', 0)
                        sensitivity_level = analysis_result.get('sensitivity_level', 'low')
                        ai_entities = analysis_result.get('entities', {})


                        # 2. Prepare data payload for blockchain/IPFS
                        record_data_payload = {
                            "record": medical_record_content,
                            "diagnosis": diagnosis,
                            "diagnosis_suggestions": diagnosis_suggestions,
                            "treatment": treatment,
                            "treatment_suggestions": treatment_suggestions,
                            "symptoms": symptoms,
                            "risk_score": risk_score,
                            "sensitivity_level": sensitivity_level,
                            "ai_entities": ai_entities,
                            "record_timestamp": datetime.now().isoformat() # Timestamp of record creation in data
                        }

                        # 3. Add record to blockchain
                        new_block = st.session_state.blockchain.add_record(
                            patient_id=patient_id,
                            patient_name=patient_name,
                            record_data=record_data_payload
                        )

                        st.session_state.success_message = f"记录提交成功！区块 ID: {new_block['block_id']}, IPFS 模拟哈希: {new_block['ipfs_hash'][:12]}..."
                        logging.info(f"User '{st.session_state.current_user}' added record block {new_block['block_id']} for patient {patient_id}")

                        # Display immediate feedback on risk/sensitivity (Optional - might be cleared on rerun)
                        # st.markdown(format_risk_display(risk_score), unsafe_allow_html=True)
                        # st.markdown(format_sensitivity_display(sensitivity_level), unsafe_allow_html=True)


                    except ValueError as ve: # Catch validation errors from backend
                        st.session_state.error_message = f"提交失败: {ve}"
                        logging.error(f"Record submission Value Error for patient {patient_id}: {ve}", exc_info=True)
                    except RuntimeError as rte: # Catch runtime errors from backend (IO, etc.)
                         st.session_state.error_message = f"提交失败，发生运行时错误: {rte}"
                         logging.error(f"Record submission Runtime Error for patient {patient_id}: {rte}", exc_info=True)
                    except Exception as e:
                        st.session_state.error_message = f"提交记录时发生意外错误: {e}"
                        logging.error(f"Unexpected error during record submission for patient {patient_id}: {e}", exc_info=True)

                # Rerun AFTER processing to clear form and display messages
                st.rerun()

            else:
                 # Display validation errors if any
                 st.session_state.error_message = f"提交失败，请检查以下错误：\n{error_msg}"
                 st.rerun() # Rerun to display validation errors

# --- Tab 2: Data Query & Management ---
with tab2:
    st.subheader("患者记录查询与管理")
    query_patient_id = st.text_input("输入患者ID进行查询", key="query_patient_id_input")
    include_history = st.checkbox("包含历史记录 (已修改/已删除)", key="include_history_check", value=True) # Default to showing history

    # Use a button to trigger query
    if st.button("查询记录", key="query_button") and query_patient_id:
        query_patient_id = query_patient_id.strip()
        # Clear previous messages before new query
        st.session_state.success_message = None
        st.session_state.error_message = None # Clear previous error message
        st.session_state['active_block_to_manage'] = None # Clear previous active block on new query (used for default expand)
        st.session_state['user_selected_block_id'] = None # Clear previous user selection
        st.session_state['query_results_df'] = None # Clear previous query results


        if not query_patient_id:
            # Changed st.warning to set error_message
            st.session_state.error_message = "请输入有效的患者ID。"
            # Important: Reset session states if no records found
            st.session_state['active_block_to_manage'] = None
            st.session_state['user_selected_block_id'] = None
            st.session_state['query_results_df'] = pd.DataFrame() # Store empty DataFrame

        else:
            with st.spinner(f"正在检索患者 {query_patient_id} 的记录..."):
                try:
                    # Use the new get_chain_view method to get the view list
                    records_view = st.session_state.blockchain.get_chain_view(
                        patient_id=query_patient_id,
                        include_history=include_history
                    )

                    if not records_view:
                        # Changed st.warning to set error_message
                        st.session_state.error_message = f"未找到患者ID '{query_patient_id}' 的记录 {'' if include_history else '(仅查询活动记录)'}。"
                        # Important: Reset session states if no records found
                        st.session_state['active_block_to_manage'] = None
                        st.session_state['user_selected_block_id'] = None
                        st.session_state['query_results_df'] = pd.DataFrame() # Store empty DataFrame

                    else:
                        st.success(f"找到 {len(records_view)} 条相关记录{' (含历史)' if include_history else ' (仅活动记录)'}。")

                        # --- Find the latest active block for default expander (optional) ---
                        active_block_id_for_expand = None
                        for block in records_view:
                            if block.get('current_status') == 'ACTIVE' and block.get('transaction_type') in ['CREATE', 'UPDATE']:
                                active_block_id_for_expand = block.get('block_id')
                                break # Found the latest active one

                        st.session_state['active_block_to_manage'] = active_block_id_for_expand # Store for default expand
                        # Convert the view list to DataFrame for display and charting
                        records_df = pd.DataFrame(records_view)
                        st.session_state['query_results_df'] = records_df # Store DataFrame

                except Exception as query_err:
                    st.session_state.error_message = f"查询记录时出错: {query_err}"
                    logging.error(f"Error querying records for patient {query_patient_id}: {query_err}", exc_info=True)
                    # Ensure query results are cleared on error
                    st.session_state['query_results_df'] = pd.DataFrame()
                    st.session_state['active_block_to_manage'] = None
                    st.session_state['user_selected_block_id'] = None


            # Need a rerun after query button click to display results and management form
            st.rerun()

    # --- Display Query Results if available in Session State ---
    # --- And handle management actions within this block ---
    if st.session_state.get('query_results_df') is not None and not st.session_state.get('query_results_df').empty:
        records_df = st.session_state['query_results_df'] # records_df is guaranteed to be defined here

        # --- Display Records ---
        for index, block in records_df.iterrows():
            block_id = block['block_id']
            timestamp = block.get('timestamp', '未知时间')[:19].replace('T', ' ')
            trans_type = block.get('transaction_type', '未知类型')
            status = block.get('current_status', '未知状态')
            metadata = block.get('metadata', {})
            patient_name_meta = metadata.get('patient_name', '未知姓名')

            expander_title = f"区块 {block_id} ({timestamp}) - 类型: {trans_type} - 状态: {status}"
            if status == 'ACTIVE' and trans_type in ['CREATE', 'UPDATE']:
                 expander_title += f" - {patient_name_meta}"

            with st.expander(expander_title, expanded=(block_id == st.session_state.get('active_block_to_manage'))):
                st.caption(f"区块哈希: {block.get('block_hash', 'N/A')[:16]}... | 前序哈希: {block.get('prev_hash', 'N/A')[:16]}...")
                st.write(f"**患者 ID:** {block.get('patient_id', 'N/A')}")

                if status == 'ACTIVE' and trans_type in ['CREATE', 'UPDATE']:
                    ipfs_hash = block.get('ipfs_hash')
                    encryption_key = block.get('metadata', {}).get('encryption_key')
                    if ipfs_hash and encryption_key:
                        try:
                            record_data = st.session_state.ipfs_manager.retrieve_data(ipfs_hash, encryption_key)
                            if record_data:
                                st.markdown(f"**患者姓名:** {record_data.get('patient_name', '未知')}")
                                st.markdown(f"**记录时间:** {record_data.get('record_timestamp', timestamp)}")
                                st.text_area("诊疗内容", value=record_data.get('record', '无内容'), height=150, disabled=True, key=f"display_record_{block_id}")
                                st.markdown("**AI 分析:**")
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.json({
                                        "诊断": record_data.get('diagnosis', []),
                                        "治疗": record_data.get('treatment', []),
                                        "症状": record_data.get('symptoms', []),
                                    }, expanded=False)
                                with col2:
                                    st.markdown(format_risk_display(record_data.get('risk_score', 0)), unsafe_allow_html=True)
                                    st.markdown(format_sensitivity_display(record_data.get('sensitivity_level', 'low')), unsafe_allow_html=True)
                                    st.json({
                                          "诊断建议": record_data.get('diagnosis_suggestions', []),
                                          "治疗建议": record_data.get('treatment_suggestions', []),
                                     }, expanded=False)

                                if st.session_state.is_admin:
                                     st.json({"AI 提取实体": record_data.get('ai_entities', {})}, expanded=False)

                            else:
                                 st.error(f"无法加载区块 {block_id} 的记录数据。IPFS 哈希: {ipfs_hash[:12]}...")

                        except ValueError as ve:
                             st.error(f"加载记录数据失败 (区块 {block_id}): {ve}")
                             logging.error(f"Failed to retrieve/decrypt data for block {block_id}", exc_info=True)
                        except RuntimeError as rte:
                             st.error(f"加载记录数据运行时错误 (区块 {block_id}): {rte}")
                             logging.error(f"Runtime error retrieving data for block {block_id}", exc_info=True)
                        except Exception as e:
                             st.error(f"加载记录数据时发生意外错误 (区块 {block_id}): {e}")
                             logging.error(f"Unexpected error loading data for block {block_id}", exc_info=True)
                    else:
                         st.warning(f"区块 {block_id} 元数据缺少 IPFS 哈希或加密密钥，无法加载数据。")


                elif status == 'SUPERSEDED':
                     superseded_by_block_id = metadata.get('updated_by_block', '未知')
                     st.warning(f"此记录已被区块 {superseded_by_block_id} 更新。")

                elif status == 'DELETED':
                     st.error(f"此记录已被标记为删除。")
                     if 'deleted_by' in metadata:
                          st.json({
                               "删除操作人": metadata.get('deleted_by'),
                               "删除原因": metadata.get('delete_reason'),
                               "删除时间": metadata.get('delete_timestamp', '未知')[:19].replace('T',' '),
                               "标记区块ID": metadata.get('deletion_marker_block_id', '未知')
                          })

                elif trans_type == 'DELETE' and status == 'MARKER':
                     st.info(f"这是一个删除标记区块，标记了区块 {metadata.get('deleted_block_id', '未知')} 的删除。")
                     st.json({
                          "被删除区块ID": metadata.get('deleted_block_id'),
                          "删除操作人": metadata.get('deleted_by'),
                          "删除原因": metadata.get('delete_reason'),
                          "原数据IPFS哈希": metadata.get('deleted_ipfs_hash', 'N/A')[:16]+'...',
                          "标记区块ID": block_id
                     })
                else:
                     st.write("区块元数据:")
                     st.json(metadata)

        # --- Chart ---
        chart = create_history_chart(records_df)
        if chart:
             st.altair_chart(chart, use_container_width=True)


        # --- Management Actions (Update/Delete) - Only for Admins and if records are loaded ---
        # This whole block is now inside the check for non-empty records_df
        if st.session_state.is_admin:
             # Filter for active records to provide selection options
             active_records_for_management = records_df[
                  (records_df['current_status'] == 'ACTIVE') &
                  (records_df['transaction_type'].isin(['CREATE', 'UPDATE']))
             ].copy()

             if not active_records_for_management.empty:
                  st.divider()
                  st.subheader("选择记录进行管理 (更新/删除)")

                  # Create display options for the selectbox
                  active_records_for_management['display_option'] = active_records_for_management.apply(
                      lambda row: f"区块 {row['block_id']} ({row.get('timestamp', '未知时间')[:19].replace('T', ' ')}) - {row.get('metadata', {}).get('patient_name', '未知姓名')}",
                      axis=1
                  )

                  # Determine default index for the selectbox
                  default_index = 0
                  # If there's a previous user selection in state, try to find its index
                  if 'user_selected_block_id' in st.session_state and st.session_state['user_selected_block_id'] is not None:
                      try:
                          # Find the row in active_records_for_management with the previously selected block_id
                          selected_row_index = active_records_for_management[active_records_for_management['block_id'] == st.session_state['user_selected_block_id']].index[0]
                          # Find the position of this row's display_option in the list of display options
                          default_index = active_records_for_management['display_option'].tolist().index(active_records_for_management.loc[selected_row_index, 'display_option'])
                      except (IndexError, ValueError):
                          # If the previous selection is not in the current list of options, default to the first one
                          default_index = 0
                          # Clear the invalid previous selection from session state
                          st.session_state['user_selected_block_id'] = None
                  # If no previous selection or lookup failed, default_index remains 0 (first item)


                  selected_block_display = st.selectbox(
                      "选择要管理 (更新/删除) 的记录:",
                      options=active_records_for_management['display_option'].tolist(),
                      index=default_index, # Set default based on logic above
                      key="manage_record_selector"
                  )

                  # Find the block_id corresponding to the currently selected display option
                  selected_row = active_records_for_management[active_records_for_management['display_option'] == selected_block_display]
                  selected_block_id = None
                  if not selected_row.empty:
                      # Ensure selected_block_id is an integer
                      selected_block_id = int(selected_row.iloc[0]['block_id'])
                      st.session_state['user_selected_block_id'] = selected_block_id # Store the currently selected ID
                      st.write(f"您当前选择了区块 ID: **{selected_block_id}** 进行管理。") # User confirmation

                      # --- Retrieve current content for the selected active block to pre-fill the form ---
                      current_content_for_update = ''
                      current_block_for_management = st.session_state.blockchain.get_block(selected_block_id)

                      if current_block_for_management and st.session_state.blockchain.get_block_status(selected_block_id) == 'ACTIVE': # Double check status
                          ipfs_hash_mgmt = current_block_for_management.get('ipfs_hash')
                          encryption_key_mgmt = current_block_for_management.get('metadata', {}).get('encryption_key')

                          if ipfs_hash_mgmt and encryption_key_mgmt:
                              try:
                                  current_data_mgmt = st.session_state.ipfs_manager.retrieve_data(ipfs_hash_mgmt, encryption_key_mgmt)
                                  current_content_for_update = current_data_mgmt.get('record', '') if current_data_mgmt else ''
                              except Exception as load_err_mgmt:
                                  st.warning(f"无法加载当前记录内容 (区块 {selected_block_id}) 进行修改: {load_err_mgmt}")
                                  logging.error(f"Failed to load content for update block {selected_block_id}", exc_info=True)
                          else:
                               st.warning(f"选定的活动区块 {selected_block_id} 元数据缺少 IPFS 哈希或加密密钥，无法加载内容进行修改。")
                      else:
                           st.warning(f"未能获取选定的活动区块 {selected_block_id} 的信息或其状态不是 'ACTIVE'，无法加载内容进行修改。")


                      # --- Update Form ---
                      # Use the user_selected_block_id for the update operation
                      block_id_to_update = st.session_state['user_selected_block_id']

                      # Only display update/delete forms if a block is actually selected and is ACTIVE (should be guaranteed by selectbox)
                      if block_id_to_update is not None:
                          with st.form(f"update_form_{block_id_to_update}", clear_on_submit=False): # Keep content after submit to show message
                               st.markdown("**修正记录内容** (这将创建一个新的区块版本)")

                               # Text area for new content, pre-filled with current content of the selected block
                               # Use a unique key that depends on the selected block_id to ensure it reloads when selection changes
                               new_content = st.text_area("新的诊疗内容*", value=current_content_for_update, height=200, key=f"update_content_{block_id_to_update}")
                               update_reason = st.text_input("修改原因*", key=f"update_reason_{block_id_to_update}")

                               update_submitted = st.form_submit_button("提交修改")
                               if update_submitted:
                                    st.session_state.success_message = None
                                    st.session_state.error_message = None

                                    if not new_content.strip() or not update_reason.strip():
                                         st.session_state.error_message = "新内容和修改原因都不能为空。"
                                    elif new_content.strip() == current_content_for_update.strip(): # Compare stripped content
                                          st.session_state.warning_message = "新内容与当前内容相同，无需修改。"
                                    elif block_id_to_update is None:
                                          st.session_state.error_message = "没有选定要修改的活动记录区块。"
                                    else:
                                         with st.spinner("正在处理修改..."):
                                              try:
                                                   # --- Initialize update_payload here ---
                                                   update_payload = None

                                                   # Get patient info from the block being updated
                                                   block_to_update_info = st.session_state.blockchain.get_block(block_id_to_update)
                                                   patient_id_for_update_op = block_to_update_info.get('patient_id') if block_to_update_info else None
                                                   patient_name_for_update_op = block_to_update_info.get('metadata', {}).get('patient_name', '未知') if block_to_update_info else '未知'

                                                   if not patient_id_for_update_op:
                                                        st.session_state.error_message = "无法获取区块的患者ID，修改失败。"
                                                        logging.error(f"Cannot get patient ID for block {block_id_to_update} during update.")
                                                        st.rerun()


                                                   # --- Perform analysis and define update_payload ---
                                                   analysis_result = st.session_state.analyzer.analyze_text(new_content.strip(), patient_name_for_update_op)
                                                   analysis_result = analysis_result if analysis_result else {}

                                                   # Define update_payload only if analysis was successful (analysis_result is not empty/None dict)
                                                   # Added check for analysis_result to ensure it's a dictionary before accessing .get()
                                                   if isinstance(analysis_result, dict) and analysis_result: # Check if analysis_result is a non-empty dictionary
                                                        update_payload = {
                                                             "record": new_content.strip(),
                                                             "diagnosis": analysis_result.get('diagnosis', []),
                                                             "diagnosis_suggestions": analysis_result.get('diagnosis_suggestions', []),
                                                             "treatment": analysis_result.get('treatment', []),
                                                             "treatment_suggestions": analysis_result.get('treatment_suggestions', []),
                                                             "symptoms": analysis_result.get('symptoms', []),
                                                             "risk_score": analysis_result.get('risk_score', 0),
                                                             "sensitivity_level": analysis_result.get('sensitivity_level', 'low'),
                                                             "ai_entities": analysis_result.get('entities', {}),
                                                             "record_timestamp": datetime.now().isoformat()
                                                        }
                                                   else:
                                                        # Handle case where analysis failed or returned empty result or wrong type
                                                        st.session_state.error_message = "数据分析失败或返回无效结果，无法创建更新内容。"
                                                        logging.error(f"Analysis failed or returned invalid result for block {block_id_to_update}, update_payload not created. Analysis result: {analysis_result}")
                                                        st.rerun() # Rerun to display error


                                                   # --- Use update_payload only if it was defined ---
                                                   if update_payload is not None:
                                                        update_block = st.session_state.blockchain.update_record_content(
                                                             original_block_id=block_id_to_update,
                                                             new_record_data=update_payload,
                                                             user=st.session_state.current_user,
                                                             reason=update_reason.strip()
                                                        )
                                                        st.session_state.success_message = f"记录修正成功！新的区块 ID: {update_block['block_id']}"
                                                        # Need the patient ID from the original block for logging
                                                        block_to_update_info_log = st.session_state.blockchain.get_block(block_id_to_update)
                                                        patient_id_for_update_op_log = block_to_update_info_log.get('patient_id', '未知') if block_to_update_info_log else '未知'


                                                        logging.info(f"User '{st.session_state.current_user}' updated block {block_id_to_update} (New Block: {update_block['block_id']}) for patient {patient_id_for_update_op_log}. Reason: {update_reason.strip()}")
                                                        # Clear state to force re-query/refresh view on next interaction
                                                        st.session_state['query_results_df'] = None
                                                        st.session_state['user_selected_block_id'] = None
                                                        st.session_state['active_block_to_manage'] = None
                                                        st.rerun()
                                                   # Else: error message already set and rerun called if update_payload is None


                                              except ValueError as ve:
                                                   st.session_state.error_message = f"修改失败: {ve}"
                                                   logging.error(f"Record update Value Error for block {block_id_to_update}: {ve}", exc_info=True)
                                                   st.rerun()
                                              except RuntimeError as rte:
                                                   st.session_state.error_message = f"修改失败，发生运行时错误: {rte}"
                                                   logging.error(f"Record update Runtime Error for block {block_id_to_update}: {rte}", exc_info=True)
                                                   st.rerun()
                                              except Exception as e:
                                                   # This general exception will now catch errors during analysis or payload construction
                                                   st.session_state.error_message = f"修改记录时发生意外错误: {e}"
                                                   logging.error(f"Unexpected error during record update for block {block_id_to_update}: {e}", exc_info=True)
                                                   st.rerun()


                          # --- Delete Button ---
                          # Use the user_selected_block_id for the delete operation
                          block_id_to_delete = st.session_state['user_selected_block_id']

                          st.markdown("**删除记录** (这将添加一个删除标记区块，原记录不可再修改)")
                          # Use a unique key for the delete reason input, dependent on selected block ID
                          delete_reason = st.text_input("删除原因*", key=f"delete_reason_{block_id_to_delete}")
                          # Use a unique key for the delete button, dependent on selected block ID
                          if st.button("确认删除", key=f"delete_button_{block_id_to_delete}", type="primary"):
                               st.session_state.success_message = None
                               st.session_state.error_message = None

                               if not delete_reason.strip():
                                    st.session_state.error_message = "删除原因不能为空。"
                                    st.rerun()
                               elif block_id_to_delete is None:
                                    st.session_state.error_message = "没有选定要删除的活动记录区块。"
                                    st.rerun()
                               else:
                                    with st.spinner("正在处理删除..."):
                                         try:
                                             delete_marker_block = st.session_state.blockchain.delete_record(
                                                  block_id_to_delete=block_id_to_delete,
                                                  user=st.session_state.current_user,
                                                  reason=delete_reason.strip()
                                             )
                                             st.session_state.success_message = f"记录 {block_id_to_delete} 已标记为删除。删除标记区块 ID: {delete_marker_block['block_id']}"
                                             # Need the patient ID from the original block for logging
                                             block_to_delete_info = st.session_state.blockchain.get_block(block_id_to_delete)
                                             patient_id_for_delete_op_log = block_to_delete_info.get('patient_id', '未知') if block_to_delete_info else '未知'

                                             logging.info(f"User '{st.session_state.current_user}' deleted block {block_id_to_delete} (Marker Block: {delete_marker_block['block_id']}) for patient {patient_id_for_delete_op_log}. Reason: {delete_reason.strip()}")
                                             # Clear state to force re-query/refresh view on next interaction
                                             st.session_state['query_results_df'] = None
                                             st.session_state['user_selected_block_id'] = None
                                             st.session_state['active_block_to_manage'] = None
                                             st.rerun()

                                         except ValueError as ve:
                                              st.session_state.error_message = f"删除失败: {ve}"
                                              logging.error(f"Record deletion Value Error for block {block_id_to_delete}: {ve}", exc_info=True)
                                              st.rerun()
                                         except RuntimeError as rte:
                                              st.session_state.error_message = f"删除失败，发生运行时错误: {rte}"
                                              logging.error(f"Record deletion Runtime Error for block {block_id_to_delete}: {rte}", exc_info=True)
                                              st.rerun()
                                         except Exception as e:
                                              st.session_state.error_message = f"删除记录时发生意外错误: {e}"
                                              logging.error(f"Unexpected error during record deletion for block {block_id_to_delete}: {e}", exc_info=True)
                                              st.rerun()
                      else:
                          st.warning("未能获取选定的区块信息，无法进行管理操作。")


             else:
                  # If active_records_for_management is empty, even if records_df is not
                  st.info("该患者没有活动状态 (ACTIVE) 的记录可供更新或删除。")
                  st.session_state['user_selected_block_id'] = None # Ensure selection is cleared

        # If not admin, the management actions section within this block is skipped
    elif st.session_state.is_admin:
         # If admin, but query_results_df is None or empty
         st.divider()
         st.subheader("选择记录进行管理 (更新/删除)")
         st.info("请先查询患者记录，并且确保有活动状态 (ACTIVE) 的记录可供管理。")
         st.session_state['user_selected_block_id'] = None # Ensure selection is cleared

    # If not admin, the whole management section is skipped by the outer if

# --- Tab 3: System Management ---
with tab3:
    st.subheader("系统管理")

    if not st.session_state.is_admin:
        st.warning("此区域需要管理员权限。")
    else:
        st.success("管理员权限已激活。")

        # --- System Status ---
        with st.expander("系统状态与统计"):
            try:
                # Blockchain Stats
                # Get chain directly from the blockchain instance
                chain = st.session_state.blockchain.chain
                total_blocks = len(chain)
                st.write(f"**区块链总区块数**: {total_blocks} (包含 Genesis 和标记区块)")
                if total_blocks > 0:
                     # Get timestamp from the last block
                     last_block_time = chain[-1].get('timestamp', 'N/A')
                     if last_block_time != 'N/A':
                          # Format timestamp nicely
                          last_block_time = last_block_time[:19].replace('T', ' ')
                     st.write(f"**最后区块时间**: {last_block_time}")
                else:
                     st.write("区块链为空或未加载。")

                # IPFS Storage Stats
                # Get stats from the ipfs_manager instance
                ipfs_stats = st.session_state.ipfs_manager.get_storage_stats()
                st.write(f"**IPFS 存储记录数**: {ipfs_stats.get('total_records', 'N/A')}")
                size_mb = ipfs_stats.get('total_encrypted_size_bytes', 0) / (1024 * 1024) # Convert bytes to MB
                st.write(f"**IPFS 存储总大小 (加密后)**: {size_mb:.2f} MB")
                st.write("**按敏感度统计:**")
                st.json(ipfs_stats.get('sensitivity_stats', {}))
                if ipfs_stats.get('file_consistency_errors', 0) > 0:
                     st.warning(f"**IPFS 文件一致性错误**: {ipfs_stats.get('file_consistency_errors')}")

            except Exception as e:
                st.error(f"获取系统状态失败: {e}")
                logging.error("Failed to retrieve system status", exc_info=True)

        # --- Backup ---
        with st.expander("数据备份"):
            st.info("将创建当前 IPFS 存储和区块链文件的备份。")
            # Ensure backup button has a unique key
            if st.button("创建备份", key="create_backup_button"):
                with st.spinner("正在创建备份..."):
                    try:
                         # Backup IPFS storage
                         ipfs_backup_path = st.session_state.ipfs_manager.backup_storage()
                         # Backup Blockchain file
                         ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                         backup_bc_file = f"{BLOCKCHAIN_FILE}_backup_{ts}.jsonl" # Add .jsonl extension
                         # Ensure the data directory exists before copying (DATA_DIR should be imported from blockchain.py)
                         # import is already at the top: from blockchain import MedicalBlockchain, BLOCKCHAIN_FILE
                         # Need to ensure DATA_DIR is also imported if used here directly. Let's use os.path.dirname(BLOCKCHAIN_FILE)
                         backup_dir = os.path.dirname(backup_bc_file)
                         os.makedirs(backup_dir, exist_ok=True)

                         # Check if blockchain file exists before attempting to copy
                         if not os.path.exists(BLOCKCHAIN_FILE):
                              raise FileNotFoundError(f"Blockchain file not found at {BLOCKCHAIN_FILE}. Please ensure the system has run at least once.")

                         shutil.copy2(BLOCKCHAIN_FILE, backup_bc_file) # copy2 preserves metadata

                         st.session_state.success_message = f"备份成功！\nIPFS 备份: {ipfs_backup_path}\n区块链备份: {backup_bc_file}"
                         logging.info(f"User '{st.session_state.current_user}' created backup. IPFS: {ipfs_backup_path}, Blockchain: {backup_bc_file}")

                    except FileNotFoundError as fnfe:
                         st.session_state.error_message = f"备份失败：文件未找到。{fnfe}"
                         logging.error(f"Backup failed: File not found. {fnfe}", exc_info=True)
                         st.rerun() # Rerun to display error
                    except Exception as e:
                         st.session_state.error_message = f"备份失败: {e}"
                         logging.error("Backup failed", exc_info=True)
                         st.rerun() # Rerun to display error
                # Rerun after successful backup attempt to display messages
                st.rerun()


        # --- Super Admin Only Section ---
        if st.session_state.is_super_admin:
            st.divider()
            st.subheader("超级管理员操作")
            st.warning("⚠️ 以下操作具有风险性，请谨慎使用！")

            with st.expander("清空数据 (危险!)", expanded=False):
                st.markdown("**此操作将永久删除所有 IPFS 存储数据和区块链记录！**")
                # Ensure confirmation checkbox has a unique key
                confirm_clear = st.checkbox("我确认要清空所有数据，此操作不可逆。", key="confirm_clear_checkbox")
                # Ensure password input has a unique key
                super_admin_pass_clear = st.text_input("再次输入超级管理员密码确认", type="password", key="clear_pass_input")

                # Ensure clear button has a unique key
                if st.button("确认清空所有数据", key="clear_all_data_button", type="primary"):
                    # Clear previous messages before clear attempt
                    st.session_state.success_message = None
                    st.session_state.error_message = None

                    if confirm_clear and super_admin_pass_clear == SUPER_ADMIN_PASSWORD:
                        with st.spinner("正在清空所有数据..."):
                            try:
                                # Clear Blockchain first (handles its own index/file)
                                # Pass password to blockchain clear method
                                st.session_state.blockchain.clear_all_data(super_admin_pass_clear)
                                # Clear IPFS storage (pass confirmation flag and password for double check)
                                st.session_state.ipfs_manager.clear_storage(super_admin_pass_clear, confirm=True)

                                st.session_state.success_message = "所有 IPFS 存储和区块链数据已成功清空并重置。"
                                logging.critical(f"!!! Super Admin '{st.session_state.current_user}' cleared ALL data !!!")
                                # Clear any displayed query results or active management state
                                st.session_state['query_results_df'] = None
                                st.session_state['active_block_to_manage'] = None
                                st.rerun()
                            except PermissionError as pe:
                                 st.session_state.error_message = f"清空失败: {pe}"
                                 logging.error(f"Clear data permission error: {pe}", exc_info=True)
                                 st.rerun() # Rerun to display error
                            except Exception as e:
                                st.session_state.error_message = f"清空数据时发生错误: {e}"
                                logging.error("Clear all data failed", exc_info=True)
                                st.rerun() # Rerun to display error
                            # Rerun after successful clear attempt to display messages
                            st.rerun()
                    elif not confirm_clear:
                         st.session_state.error_message = "必须勾选确认框才能执行清空操作。"
                         st.rerun() # Rerun to display error
                    else:
                         st.session_state.error_message = "超级管理员密码错误！清空操作未执行。"
                         logging.warning(f"Failed clear data attempt by '{st.session_state.current_user}': Incorrect password.")
                         st.rerun() # Rerun to display error


            # Note: Modifying hardcoded passwords via UI is not implemented.
            # In a real app, password changes would involve secure storage updates.
            with st.expander("密码管理 (示例)", expanded=False):
                 st.info("在此模拟版本中，管理员和超级管理员密码是硬编码的，无法通过界面修改。")
                 st.write(f"当前管理员密码 (示例): `{ADMIN_PASSWORD}`")
                 st.write(f"当前超级管理员密码 (示例): `{SUPER_ADMIN_PASSWORD}`")


# ============ Footer ============\
st.divider()
st.caption(f"医疗数据管理系统 v6.0 (模拟模式) | {datetime.now().year}")
logging.info("Application UI rendered.")