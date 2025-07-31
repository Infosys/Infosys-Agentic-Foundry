# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
from dotenv import load_dotenv
from pathlib import Path
import httpx
import streamlit as st
import pandas as pd
import json
import requests
import ast
from MultiDBConnection_Manager import get_connection_manager
load_dotenv()
ENDPOINT_URL_PREFIX = os.getenv("ENDPOINT_URL_PREFIX")

#Directory to store the DB file for sqlite in dataconnector
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploaded_sqlite_dbs")
os.makedirs(UPLOAD_DIR, exist_ok=True)

try:
    model_options = requests.get(f"{ENDPOINT_URL_PREFIX}/get-models").json()
    model_options = model_options['models']
except:
    model_options = ["gpt-4o"]

st.set_page_config(
    page_title="Infosys Agentic Foundry",
    layout="wide"
)

# Global CSS for consistent styling throughout the app
def set_global_styles():
    """
    Sets custom global CSS styles for the Streamlit application.

    This function applies various styling rules to different components of the Streamlit app:
    - Adjusts the padding, font sizes, and colors for headers (h1, h2, h3, h4).
    - Defines styles for input fields, select boxes, text areas, and buttons.
    - Customizes the appearance of tables, chat messages, and status messages.
    - Applies styles for the sidebar, including background colors.
    - Ensures that chat messages from the user and assistant are styled distinctly.

    All styles are applied using inline CSS via the `st.markdown()` method with the
    `unsafe_allow_html=True` flag to render the custom styles.

    Returns:
        None
    """
    st.markdown("""
        <style>
        /* Global styles */
        .main {
            padding: 2rem;
        }

        /* Header styles */
        h1 {
            color: #1E3250;
            font-size: 2.5rem;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid #FF4B4B;
        }

        h2 {
            color: #1E3250;
            font-size: 1.8rem;
            margin-bottom: 1.5rem;
        }

        h3, h4 {
            color: #2C3E50;
            margin: 1rem 0;
        }

        /* Input field styles */
        .stTextInput > div > div > input,
        .stSelectbox > div > div > select {.
            background-color: #f8f9fa;
            color: black;
            caret-color: black;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 0.75rem;
            font-size: 1rem;
        }

        .stTextArea > div > div > textarea {
            background-color: #f8f9fa;
            color: black;
            caret-color: black;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 0.75rem;
            font-size: 1rem;
            min-height: 100px;
        }

        /* Button styles */


        .stButton > button:hover {
            background-color: #c3e4fa;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }

        /* Table styles */
        .dataframe {
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 1rem;
        }

        /* Chat styles */
        .chat-container {
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem 0;
            max-height: 600px;
            overflow-y: auto;
        }

        .user-message {
            float: right;
            color: blue;
            background-color: #e0f7fa;
            margin: 5px;
            padding: 5px 20px;
            border-radius: 10px;
            max-width: 80%;
            width: fit-content;
            clear: both;
        }

        .assistant-message {
            color: green;
            background-color: #e8f5e9;
            margin: 5px;
            padding: 5px 20px;
            border-radius: 10px;
            max-width: 80%;
            width: fit-content;
            clear: both;
        }


        /* Section divider */
        .section-divider {
            margin: 2rem 0;
            border-top: 1px solid #dee2e6;
        }

        /* Sidebar styles */
        .css-1d391kg {
            background-color: #f8f9fa;
        }

        /* Status messages */
        .success-message {
            background-color: #e8f5e9;
            color: #2e7d32;
            padding: 1rem;
            border-radius: 6px;
            margin: 1rem 0;
        }

        .error-message {
            background-color: #ffebee;
            color: #c62828;
            padding: 1rem;
            border-radius: 6px;
            margin: 1rem 0;
        }
        </style>
    """, unsafe_allow_html=True)


def manage_tags():
    with st.popover("Manage Tags"):
        try:
            available_tags = requests.get(f"{ENDPOINT_URL_PREFIX}/tags/get-available-tags", timeout=None).json()
            tags_df = pd.DataFrame(available_tags)
            disabled_columns = tags_df.columns
            tags_df.insert(0, "Select", False)
        except Exception as e:
            st.toast(f"Unable to fetch available tags: {e}")
            tags_df = pd.DataFrame()

        create_tab, update_tab, delete_tab = st.tabs(["Create Tag", "Update Tag", "Delete Tag"])
        with create_tab:
            with st.form("Create Tag"):
                tag_name = st.text_input("Tag Name:", placeholder="Enter tag name")
                created_by = st.text_input("Created By:", placeholder="Enter your email (example@infosys.com)")
                if st.form_submit_button("Create Tag"):
                    if not tag_name or not created_by:
                        st.toast("Please fill all the details", icon="⚠️")
                        return
                    payload = {
                        "tag_name": tag_name,
                        "created_by": created_by
                    }
                    try:
                        response = requests.post(f"{ENDPOINT_URL_PREFIX}/tags/create-tag", json=payload, timeout=None).json()
                        st.toast(response["message"])
                    except Exception as e:
                        st.toast(f"Error occured: {e}")
                if isinstance(tags_df, pd.DataFrame):
                    st.dataframe(tags_df['tag_name'])


        with update_tab:
            if isinstance(tags_df, pd.DataFrame):
                tags_df_editor = tags_df.drop(columns='tag_id')
                tags_df_editor = st.data_editor(tags_df_editor, disabled=disabled_columns, key="tags_on_update_tab")
                tags_df_editor['tag_id'] = tags_df['tag_id']
                selected_tags = tags_df_editor[tags_df_editor['Select']]
                selected_tags_list = selected_tags['tag_id'].tolist()

                if not selected_tags_list:
                    st.info("Select a tag to edit")
                elif len(selected_tags_list) > 1:
                    st.error("You can edit only 1 tag at a time")

                else:
                    with st.form("Update Tag"):
                        updated_tag = selected_tags.iloc[0].to_dict()
                        tag_name = st.text_input("Tag Name:", placeholder="Enter tag name", value=updated_tag['tag_name'])
                        created_by = st.text_input("Created By:", placeholder="Enter your email (example@infosys.com)")
                        updated_tag['new_tag_name'] = tag_name
                        if st.form_submit_button("Update Tag"):
                            if not tag_name or not created_by:
                                st.toast("Please fill all the details", icon="⚠️")
                                return
                            if updated_tag['created_by'] != created_by:
                                st.toast("You don't have permission to update this tag")
                                return
                            try:
                                response = requests.put(f"{ENDPOINT_URL_PREFIX}/tags/update-tag", json=updated_tag, timeout=None).json()
                                st.toast(response["message"])
                            except Exception as e:
                                st.toast(f"Error occured: {e}")


        with delete_tab:
            if isinstance(tags_df, pd.DataFrame):
                tags_df_editor = tags_df.drop(columns='tag_id')
                tags_df_editor = st.data_editor(tags_df_editor, disabled=disabled_columns, key="tags_on_delete_tab")
                tags_df_editor['tag_id'] = tags_df['tag_id']
                selected_tags = tags_df_editor[tags_df_editor['Select']]
                selected_tags_list = selected_tags['tag_id'].tolist()

                if not selected_tags_list:
                    st.info("Select a tag to delete")
                elif len(selected_tags_list) > 1:
                    st.error("You can delete only 1 tag at a time")

                else:
                    with st.form("Delete Tag"):
                        tag_to_del = selected_tags.iloc[0].to_dict()
                        created_by = st.text_input("Created By:", placeholder="Enter your email (example@infosys.com)")
                        if st.form_submit_button("Delete Tag"):
                            if not created_by:
                                st.toast("Please fill all the details", icon="⚠️")
                                return
                            if tag_to_del['created_by'] != created_by:
                                st.toast("You don't have permission to update this tag")
                                return
                            try:
                                response = requests.delete(f"{ENDPOINT_URL_PREFIX}/tags/delete-tag", json=tag_to_del, timeout=None).json()
                                st.toast(response["message"])
                            except Exception as e:
                                st.toast(f"Error occured: {e}")


# Tools Onboarding

def onboard_tool():

    """
    Handles the onboarding of a new tool via a Streamlit interface.

    Allows the user to:
        Add Tool, Update Tool and Delete Tool.

    Returns:
        None
    """
    st.markdown("<br>", unsafe_allow_html=True)
    # Display existing tools in a styled table
    col1, col2, col3 = st.columns([1, 1.2, 0.8])
    with col1:
        action = st.selectbox(
            "Select Action", ["Add Tool", "Update Tool", "Delete Tool"])
    with col3:
        try:
            manage_tags()
        except Exception as e:
            st.toast(f"Unable to fetch available tags: {e}")

    if action == "Add Tool":
        st.markdown("<h3>Available Tools</h3>", unsafe_allow_html=True)
        try:
            available_tags = requests.get(
                f"{ENDPOINT_URL_PREFIX}/tags/get-available-tags", timeout=None).json()
            filter_required_tags_df = pd.DataFrame(available_tags)
            selected_tags = st.multiselect(
                "Select tags to filter",
                options=filter_required_tags_df['tag_name'].tolist(),
                key="selected_tags_to_filter"
            )
            if selected_tags:
                payload_tags = {"tag_names": selected_tags}
                tools = requests.post(
                    f"{ENDPOINT_URL_PREFIX}/tags/get-tools-by-tag", json=payload_tags, timeout=None).json()
            else:
                tools = requests.get(
                    f"{ENDPOINT_URL_PREFIX}/get-tools", timeout=None).json()

            tool_df = pd.DataFrame(tools)
            tool_df['tags'] = tool_df['tags'].apply(lambda x: str([tag['tag_name'] for tag in x]))
            tool_df.insert(2, 'tags', tool_df.pop('tags'))
            tool_df.index = tool_df.index+1
            tool_df1 = tool_df.drop(columns=['tool_id'])
            st.dataframe(tool_df1, use_container_width=True)

        except requests.exceptions.ReadTimeout:
            st.toast(f"Error: Request Timeout!")
        except ValueError:
            st.toast("No Tools Available.")
        except Exception as e:
            st.toast(e)

        st.markdown("<h2>Onboard Tool</h2>", unsafe_allow_html=True)
        st.markdown("<div class='section-divider'></div>",
                    unsafe_allow_html=True)
        # Tool input form
        with st.form("tool_form"):
            tags_df = pd.DataFrame(available_tags)

            tool_description = st.text_input(
                "Tool Description", placeholder="Enter a detailed description of the tool")
            selected_tags_for_tool = st.multiselect(
                "Select tags for the tool",
                options=tags_df['tag_name'].tolist(),
                key="selected_tags_for_tool"
            )
            code_snippet = st.text_area(
                "Code Snippet", placeholder="Paste your code here", height=200)

            col1, col2 = st.columns([1, 2])
            with col1:
                model_name = st.selectbox("Model",
                                          options=model_options,
                                          index=(0 if "gpt-4o" not in model_options else model_options.index("gpt-4o")),
                                          placeholder="Select model")
            with col2:
                created_by = st.text_input(
                    "Created By", placeholder="Enter your email (example@infosys.com)")
            submitted = st.form_submit_button("Add Tool")
        if submitted:
            if not all([tool_description, code_snippet, model_name, created_by]):
                st.markdown(
                    "<div class='error-message'>⚠️Please fill all required fields</div>",
                    unsafe_allow_html=True)
                return None

            tag_id_list = tags_df[tags_df['tag_name'].isin(selected_tags_for_tool)]['tag_id'].tolist()
            tool_data = {
                "tool_description": tool_description,
                "code_snippet": code_snippet,
                "model_name": model_name,
                "created_by": created_by,
                "tag_ids": tag_id_list
            }
            if tool_data:
                with st.spinner('Adding tool...'):
                    status = requests.post(
                        f"{ENDPOINT_URL_PREFIX}/add-tool", json=tool_data, timeout=None)
                    status = status.json()
                    if status:
                        if status["is_created"] is True:
                            st.markdown(
                                "<div class='success-message'>✅ Tool added successfully!</div>",
                                unsafe_allow_html=True)
                            st.markdown(
                                "<div class='section-divider'></div>", unsafe_allow_html=True)
                            st.write(status)
                            st.markdown(
                                "<div class='section-divider'></div>", unsafe_allow_html=True)
                            st.markdown("<h3>Updated Tools Table</h3>",
                                        unsafe_allow_html=True)
                            tools = requests.get(
                                f"{ENDPOINT_URL_PREFIX}/get-tools", timeout=None)
                            tools = tools.json()
                            st.dataframe(pd.DataFrame(tools),
                                         use_container_width=True)
                        elif status["is_created"] is False:
                            st.markdown(
                                "<div class='error-message'>⚠️ Error adding tool</div>",
                                unsafe_allow_html=True)
                            st.markdown(
                                "<div class='section-divider'></div>",
                                unsafe_allow_html=True)
                            st.write(status)

    elif action == "Update Tool":
        st.markdown("<h2>Update Tool</h2>", unsafe_allow_html=True)
        st.markdown("<div class='section-divider'></div>",
                    unsafe_allow_html=True)

        try:
            tools = requests.get(
                f"{ENDPOINT_URL_PREFIX}/get-tools", timeout=None)
            tools = tools.json()
            available_tags = requests.get(f"{ENDPOINT_URL_PREFIX}/tags/get-available-tags", timeout=None).json()
            available_tags_df = pd.DataFrame(available_tags)
            df = pd.DataFrame(tools)
        except requests.exceptions.ReadTimeout:
            st.write(f"Error: Request Timeout!")
            return
        except ValueError:
            st.write("No Tools Available.")
            return
        except Exception as e:
            st.write(e)
            return

        st.write('Select the tool you want to update:')
        df.index = df.index+1
        disabled_columns = df.columns
        tags_series = df['tags']
        df['tags'] = df['tags'].apply(lambda x: str([tag['tag_name'] for tag in x]))
        df.insert(2, 'tags', df.pop('tags'))
        # Add a checkbox column
        df.insert(0, 'Selected', False)
        # Create a checkbox for each row
        df1 = df.drop(columns=['tool_id'])
        tool_df = st.data_editor(df1, disabled=disabled_columns)
        tool_df['tool_id'] = df['tool_id']
        tool_df['tags_details'] = tags_series
        selected_tools = tool_df[tool_df['Selected'] == True]
        if len(selected_tools) > 1:
            st.write('You can only select 1 tool at a time')
            # st.write('Select the Agent you want to update:')
        elif len(selected_tools) == 0:
            st.write('Please select one tool')
        else:
            st.write("Selected Tool ID:")
            st.write(selected_tools[selected_tools['Selected']]['tool_id'].values[0])

            with st.form("tool_form"):
                new_tool_description = st.text_input(
                    "Tool Description",
                    selected_tools[selected_tools['Selected']]
                    ['tool_description'].values[0],
                    placeholder="Enter a detailed description of the tool"
                )

                updated_tag_name_list = st.multiselect(
                    "Selected Tags",
                    options=available_tags_df['tag_name'].tolist(),
                    default=ast.literal_eval(selected_tools['tags'].iloc[0])
                )

                new_code_snippet = st.text_area(
                    "Code Snippet",
                    selected_tools[selected_tools['Selected']]
                    ['code_snippet'].values[0],
                    placeholder="Paste your code here",
                    height=200
                )

                col1, col2 = st.columns([1, 2])
                with col1:
                    new_model_name = st.selectbox(
                                                "Model",
                                                options=model_options,
                                                index=(0 if "gpt-4o" not in model_options else model_options.index("gpt-4o"))
                                            )
                with col2:
                    user = st.text_input(
                        "User ID", placeholder="Enter your email (example@infosys.com)")
                submitted = st.form_submit_button("Update")

            if submitted:
                updated_tag_id_list = available_tags_df[available_tags_df['tag_name'].isin(updated_tag_name_list)]['tag_id'].tolist()

                if user:
                    new_tool_data = {
                        "tool_description": new_tool_description,
                        "code_snippet": new_code_snippet,
                        "model_name": new_model_name,
                        "user_email_id": user,
                        "updated_tag_id_list": updated_tag_id_list
                    }
                    tool_id = selected_tools[selected_tools['Selected']
                                            == True]['tool_id'].values[0]
                    url = f"{ENDPOINT_URL_PREFIX}/update-tool/{tool_id}"

                    update_status = requests.put(
                        url,
                        json=new_tool_data,
                        timeout=None
                    )

                    update_status = update_status.json()
                    st.write(update_status)
                    if not update_status.get("is_update"):
                        return None
                    if update_status["is_update"] is True:
                        st.markdown(
                            "<div class='success-message'>✅Tool Updated successfully!</div>",
                            unsafe_allow_html=True)
                        st.write("Updated Tool Details:")
                        tool_id = selected_tools[selected_tools['Selected']
                                                == True]['tool_id'].values[0]
                        url = f"{ENDPOINT_URL_PREFIX}/get-tool/{tool_id}"

                        updated_tool = requests.get(url, timeout=None)

                        updated_tool = updated_tool.json()
                        updated_tool = pd.DataFrame(updated_tool)
                        updated_tool.index = updated_tool.index+1
                        st.write(updated_tool)
                else:
                    st.write("Please enter your email id")

    elif action == "Delete Tool":
        st.markdown("<h2>Delete Tool</h2>",
                    unsafe_allow_html=True)
        st.markdown("<div class='section-divider'></div>",
                    unsafe_allow_html=True)

        try:
            tools = requests.get(
                f"{ENDPOINT_URL_PREFIX}/get-tools", timeout=None)
            tools = tools.json()
            df = pd.DataFrame(tools)
            tags_series = df['tags']
            df['tags'] = df['tags'].apply(lambda x: str([tag['tag_name'] for tag in x]))
            df.insert(2, 'tags', df.pop('tags'))
        except requests.exceptions.ReadTimeout:
            st.write(f"Error: Request Timeout!")
            return
        except ValueError:
            st.write("No Tools Available.")
            return
        except Exception as e:
            st.write(e)
            return

        st.write('Select the tool you want to Delete:')
        df.index = df.index+1
        disabled_columns = df.columns
        # Add a checkbox column
        df.insert(0, 'Selected', False)
        # Create a checkbox for each row
        df1 = df.drop(columns='tool_id')
        tool_df = st.data_editor(df1, disabled=disabled_columns)
        tool_df['tool_id'] = df['tool_id']
        selected_tools = tool_df[tool_df['Selected'] == True]
        if len(selected_tools) > 1:
            st.write('You can only select 1 tool at a time')
            # st.write('Select the Agent you want to update:')
        elif len(selected_tools) == 0:
            st.write('Please select one tool to Delete')
        else:
            st.write("Selected Tool ID:")
            st.write(
                selected_tools[selected_tools['Selected'] == True]['tool_id'].values[0])
            with st.form("tool_form"):
                user_id = st.text_input(
                    "User ID", placeholder="Enter your email (example@infosys.com)")
                submitted = st.form_submit_button("Delete")
                if submitted:
                    delete_request = {
                        "user_email_id": user_id
                    }
                    selected_tool_id = selected_tools.query(
                        'Selected == True')['tool_id'].iloc[0]
                    delete_url = f"{ENDPOINT_URL_PREFIX}/delete-tool/{selected_tool_id}"
                    delete_status = requests.delete(delete_url,
                                                    json=delete_request, timeout=None).json()
                    if delete_status["is_delete"] is False:
                        st.markdown(
                            "<div class='error-message'>⚠️ Error Deleting tool</div>",
                            unsafe_allow_html=True)
                        st.error(delete_status["status_message"])
                    else:
                        if delete_status["is_delete"] is True:
                            st.markdown(
                                "<div class='success-message'>✅ Tool Deleted successfully!</div>",
                                unsafe_allow_html=True)
                            st.success(delete_status["status_message"])
                            tools = requests.get(
                                f"{ENDPOINT_URL_PREFIX}/get-tools", timeout=None)
                            tools = tools.json()
                            st.markdown("<h3>Updated Tools</h3>",
                                        unsafe_allow_html=True)
                            tool_df = pd.DataFrame(tools)
                            st.dataframe(tool_df, use_container_width=True)


def select_tool(payload_tags=None):
    """
    Displays a table of available tools with checkboxes for selection.

    Fetches the list of tools from the backend, displays them in a table with an additional
    checkbox column for selection, and returns the IDs of the selected tools.

    Returns:
        list: A list of tool IDs for the tools that the user selected.
    """
    tools = []
    try:
        if isinstance(payload_tags, dict) and payload_tags.get('tag_names', None):
            tools = requests.post(
                f"{ENDPOINT_URL_PREFIX}/tags/get-tools-by-tag", json=payload_tags, timeout=None).json()
        else:
            tools = requests.get(f"{ENDPOINT_URL_PREFIX}/get-tools", timeout=None).json()
        tool_df = pd.DataFrame(tools)
    except Exception as e:
        # st.write(f"Error occured: {e}")
        return []
    tool_df['tags'] = tool_df['tags'].apply(lambda x: str([tag['tag_name'] for tag in x]))
    tool_df.insert(2, 'tags', tool_df.pop('tags'))
    tool_df.index = tool_df.index+1

    disabled_columns = tool_df.columns
    # Add a checkbox column
    tool_df.insert(0, 'Selected', False)

    # Create a checkbox for each row
    st.write("Select the tools you want to use:")
    df = tool_df
    tool_df = tool_df.drop(columns='tool_id')
    tool_df = st.data_editor(tool_df, disabled=disabled_columns)
    tool_df['tool_id'] = df['tool_id']
    selected_tool_ids = tool_df[tool_df['Selected']]['tool_id'].tolist()
    # st.write(selected_tool_ids)
    return selected_tool_ids




# Agent Onboarding

def display_agents(params=None, payload_tags=None):
    """
    Fetches and displays a list of agents from the backend.

    Makes a request to the backend to retrieve agent data, converts the response into a DataFrame,
    adjusts the index to start from 1, and returns the DataFrame.

    Returns:
        pd.DataFrame: A DataFrame containing the agent details, with the index starting from 1.
    """
    if isinstance(payload_tags, dict) and payload_tags.get('tag_names', None):
        agents = requests.post(
            f"{ENDPOINT_URL_PREFIX}/tags/get-agents-by-tag", json=payload_tags)
    else:
        agents = requests.get(
            f"{ENDPOINT_URL_PREFIX}/get-agents", params=params, timeout=None)
    agents = agents.json()
    agents_df = pd.DataFrame(agents)
    if params:
        param_agentic_application_type = params['agentic_application_type']
        if isinstance(param_agentic_application_type, str):
            param_agentic_application_type = [param_agentic_application_type]
        agents_df = agents_df[agents_df['agentic_application_type'].isin(param_agentic_application_type)]
    agents_df.index = agents_df.index+1
    return agents_df


def select_agent(params=None, payload_tags=None):
    """
    Displays a list of agents with checkboxes for selection and returns the selected agents.

    Fetches the agent data using `display_agents()`, adds a checkbox column for selection,
    allows the user to select agents through a table editor, and returns both the selected agents
    and the full agents DataFrame (including the checkbox column).

    Returns:
        tuple: A tuple containing:
            - pd.DataFrame: A DataFrame of selected agents.
            - pd.DataFrame: The full agents DataFrame with checkboxes.
    """
    agents_df = display_agents(params, payload_tags)
    disabled_columns = agents_df.columns
    # Add a checkbox column
    agents_df.insert(0, 'Selected', False)
    # Create a checkbox for each row
    df = agents_df
    agents_df = agents_df.drop(columns='agentic_application_id')
    tags_series = agents_df['tags']
    agents_df['tags'] = agents_df['tags'].apply(lambda x: str([tag['tag_name'] for tag in x]))
    agents_df.insert(2, 'tags', agents_df.pop('tags'))
    agents_df = st.data_editor(agents_df, disabled=disabled_columns)
    agents_df['agentic_application_id'] = df['agentic_application_id']
    agents_df['tags_details'] = tags_series
    selected_agents = agents_df[agents_df['Selected'] == True]
    return selected_agents, agents_df


def define_agent():
    """
    Creates a Streamlit page for defining agent details with improved styling.
    """
    st.markdown("<br>", unsafe_allow_html=True)
    # Page title with custom styling
    col1, col2, col3 = st.columns([1, 1.2, 0.8])
    with col1:
        action = st.selectbox(
            "Select Action", ["Create Agent", "Update Agent", "Delete Agent"])
    with col3:
        try:
            manage_tags()
        except Exception as e:
            st.toast(f"Unable to fetch available tags: {e}")

    if action == "Create Agent":
        st.markdown("<h2 style='text-align: left; font-weight: bold; margin-bottom: 30px;'>Onboard Agent</h2>",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        with cols[0]:
            agent_template = st.selectbox("Agent Template",
                                      options=["React Agent",
                                               "Multi Agent",
                                               "Planner Executor Agent",
                                               "React Critic Agent",
                                               "Meta Agent",
                                               "Planner Meta Agent"],
                                      index=None,
                                      placeholder="--Select--",
                                      help="Choose the agent template")
        # Tool selection
        selected_tool_ids = []
        try:
            available_tags = requests.get(f"{ENDPOINT_URL_PREFIX}/tags/get-available-tags", timeout=None).json()
            tags_df = pd.DataFrame(available_tags)
            selected_tags_tool_to_onboarding_agent = st.multiselect(
                "Select tags to filter tools",
                options=tags_df['tag_name'].tolist(),
                key="selected_tags_to_filter_tools"
            )

            payload_tags={"tag_names": selected_tags_tool_to_onboarding_agent}
            if agent_template == "Meta Agent" or agent_template == "Planner Meta Agent":
                params = {"agentic_application_type": ["react_agent", "multi_agent"]}
                selected_agents_df, agents_df_editor = select_agent(
                                                            params=params,
                                                            payload_tags=payload_tags
                                                        )
                selected_tool_ids = selected_agents_df["agentic_application_id"].tolist()
            else:
                selected_tool_ids = select_tool(payload_tags=payload_tags)

            st.markdown("<br>", unsafe_allow_html=True)
            if selected_tool_ids:
                st.markdown("##### Selected Tool IDs:")
                st.write(selected_tool_ids)
                st.markdown("<hr style='margin: 20px 0px;'>",
                            unsafe_allow_html=True)
        except requests.exceptions.ReadTimeout:
            st.write(f"Error: Request Timeout!")
        except ValueError as e:
            st.write("No Tools Available.")
        except Exception as e:
            st.write(f"Error: {e}")

      # Form inputs with columns
        col1, col2 = st.columns(2)
        with col1:
            agent_name = st.text_input("Agent Name:",
                                       placeholder="Enter agent name",
                                       help="Provide a unique name for your agent")
        with col2:
            email_id = st.text_input("Email Id:", placeholder='Your Email ID')

        selected_tags_for_onboarding_agent = st.multiselect(
                                                    "Select tags for the agent",
                                                    options=tags_df['tag_name'].tolist(),
                                                    key="selected_tags_for_onboarding_agent"
                                                )

        # Text areas with custom styling
        st.markdown("<div style='margin: 20px 0px;'>", unsafe_allow_html=True)
        agent_goal = st.text_area("Agent Goal:",
                                  placeholder="Write here..",
                                  height=100,
                                  help="Describe the main objective of this agent")

        workflow_description = st.text_area("Workflow Description:",
                                            placeholder="Write here..",
                                            height=150,
                                            help="Explain the workflow process in detail")


      # Model selection with columns
        col1, col2, col3 = st.columns(3)
        with col1:
            model_name = st.selectbox("Model Name:",
                                      options=model_options,
                                      index=(0 if "gpt-4o" not in model_options else model_options.index("gpt-4o")),
                                      placeholder="--Select--",
                                      help="Choose the AI model for your agent")

        # Add some spacing
        st.markdown("<br>", unsafe_allow_html=True)
        # Centered button
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            create_button = st.button("Create Agent")
        if create_button:
            if email_id:
                if not all([agent_name, agent_goal, workflow_description, model_name, agent_template]):
                    st.error("⚠️ Please fill all the required fields.")
                    return None
                tag_id_list = tags_df[tags_df['tag_name'].isin(selected_tags_for_onboarding_agent)]['tag_id'].tolist()
                agent = {
                    "agent_name": agent_name,
                    "agent_goal": agent_goal,
                    "workflow_description": workflow_description,
                    "model_name": model_name,
                    "tools_id": selected_tool_ids,
                    "email_id": email_id,
                    "tag_ids": tag_id_list
                }
                with st.spinner('Creating agent...'):
                    agent["agent_type"] = agent_template.lower().replace(" ", "_")
                    status = requests.post(f"{ENDPOINT_URL_PREFIX}/onboard-agent", json=agent, timeout=None).json()

                if status:
                    if "result" in status and status["result"]["is_created"]:
                        st.success("✅ Agent created successfully!")
                        st.markdown("<hr style='margin: 30px 0px;'>",
                                    unsafe_allow_html=True)
                        st.write(status)
                        st.markdown("<hr style='margin: 30px 0px;'>",
                                    unsafe_allow_html=True)
                        st.markdown("##### Existing Agents")
                        agents_df = display_agents()
                        st.dataframe(agents_df, use_container_width=True)
                    else:
                        st.error("⚠️Error creating agent")
                        st.markdown("<hr style='margin: 30px 0px;'>",
                                    unsafe_allow_html=True)
                        st.write(status)
            else:
                st.write('Please enter email ID')

    elif action == "Update Agent":
        st.title("Update Agent")
        st.markdown("<br>", unsafe_allow_html=True)

        try:
            st.write("Select the Agent you want to update")
            dfs = select_agent()
            selected_agents = dfs[0]
            agents_df = dfs[1]
            available_tags = requests.get(f"{ENDPOINT_URL_PREFIX}/tags/get-available-tags", timeout=None).json()
            available_tags_df = pd.DataFrame(available_tags)
            if len(selected_agents) > 1:
                st.write('You can only select 1 agent at a time')
            elif len(selected_agents) == 0:
                st.write('Please select one agent')
            else:
                agentic_application_type = selected_agents["agentic_application_type"].iloc[0]

                agent_id = agents_df[agents_df['Selected']
                                     ]['agentic_application_id'].tolist()
                st.write('Selected Agent ID : ', agent_id[0])
                with st.form("tool_form"):
                    # Display immediate reflection of input
                    updated_name = st.text_input(
                        "Agent Name", selected_agents.iloc[0]['agentic_application_name'],
                          placeholder="Enter a New name for the Agent", disabled=True)

                    updated_tag_name_list = st.multiselect(
                        "Selected Tags",
                        options=available_tags_df['tag_name'].tolist(),
                        default=ast.literal_eval(selected_agents['tags'].iloc[0])
                    )

                    current_agent_description = selected_agents.iloc[0]['agentic_application_description']
                    updated_agent_description = st.text_area(
                        "Agent Goal", current_agent_description,
                          placeholder="Enter a New description of the Agent")
                    current_application_workflow_description = selected_agents.iloc[0]['agentic_application_workflow_description']
                    updated_agent_workflow_description = st.text_area(
                        "Workflow Description", current_application_workflow_description,
                        placeholder="Enter a New Workflow description of the Agent", height=200)
                    old_system_prompts = ast.literal_eval(selected_agents.iloc[0]['system_prompt'])
                    selected_agents_current_tags = selected_agents['tags_details'].tolist()[0]
                    remaining_tags_for_selected_agent = [tag_data for tag_data in available_tags if tag_data not in selected_agents_current_tags]

                    updated_agent_system_prompts = {}

                    for prompt_name, prompt in old_system_prompts.items():
                        updated_agent_system_prompts[prompt_name] = st.text_area(
                            prompt_name,
                            prompt,
                            placeholder="Enter a New System Prompt here", height=300
                        )


                    col1, col2 = st.columns([1, 2])
                    with col1:
                        model = st.selectbox(
                                            "Model",
                                            options=model_options,
                                            index=(0 if "gpt-4o" not in model_options else model_options.index("gpt-4o")),
                                        )
                    with col2:
                        user_email = st.text_input(
                            "User ID", placeholder="Enter your email (example@infosys.com)")
                    try:
                        response = requests.get(f'{ENDPOINT_URL_PREFIX}/get-agent/{agent_id[0]}').json()
                        if agentic_application_type == "meta_agent" or agentic_application_type == "planner_meta_agent":
                            available_tools = requests.get(f"{ENDPOINT_URL_PREFIX}/get-agents", params={"agentic_application_type": ["react_agent", "multi_agent"]}).json()
                        else:
                            available_tools = requests.get(f"{ENDPOINT_URL_PREFIX}/get-tools", timeout=None).json()
                    except Exception as e:
                        response = {}
                    agent_info = pd.DataFrame(response)
                    available_tools_df = pd.DataFrame(available_tools)
                    disabled_columns = available_tools_df.columns

                    tools_ids = agent_info['tools_id'].loc[0]
                    tool_or_agent_id = 'agentic_application_id' if agentic_application_type=="meta_agent" or agentic_application_type=="planner_meta_agent" else "tool_id"
                    tools_info_df = available_tools_df[available_tools_df[tool_or_agent_id].isin(tools_ids)]
                    columns_to_show = list(tools_info_df.columns)
                    columns_to_show.remove(tool_or_agent_id)
                    columns_to_show = ["Selected"] + columns_to_show + [tool_or_agent_id]

                    tool_ids_to_remove = []
                    if not tools_info_df.empty:
                        st.write('Select tools to remove:')
                        # Add a checkbox column
                        tools_info_df.insert(0, 'Selected', False)
                        # Create a checkbox for each row
                        tools_info_df = st.data_editor(
                            tools_info_df[columns_to_show], disabled=disabled_columns)
                        selected_tools_to_remove = tools_info_df[tools_info_df['Selected'] == True]
                        tool_ids_to_remove = selected_tools_to_remove[tool_or_agent_id].tolist()


                    tool_ids_to_add = []
                    rest_tools_info_df = available_tools_df[~available_tools_df[tool_or_agent_id].isin(tools_ids)]
                    if not rest_tools_info_df.empty:
                        st.write('Select tools to add:')
                        disabled_columns = rest_tools_info_df.columns
                        # Add a checkbox column
                        rest_tools_info_df.insert(0, 'Selected', False)

                        # Create a checkbox for each row
                        rest_tools_info_df = st.data_editor(
                            rest_tools_info_df[columns_to_show], disabled=disabled_columns)
                        selected_tools_to_add = rest_tools_info_df[rest_tools_info_df['Selected'] == True]
                        tool_ids_to_add = selected_tools_to_add[tool_or_agent_id].tolist()

                    submitted = st.form_submit_button("Update Agent")
                    if submitted:
                        if user_email:
                            updated_tag_id_list = available_tags_df[available_tags_df['tag_name'].isin(updated_tag_name_list)]['tag_id'].tolist()
                            update_details = {
                                "agentic_application_id_to_modify": agent_id[0],
                                "model_name": model,
                                "user_email_id": user_email,
                                "agentic_application_description": updated_agent_description,
                                "agentic_application_workflow_description": updated_agent_workflow_description,
                                "system_prompt": updated_agent_system_prompts,
                                "tools_id_to_add": tool_ids_to_add,
                                "tools_id_to_remove": tool_ids_to_remove,
                                "is_admin": False,
                                "updated_tag_id_list": updated_tag_id_list
                            }

                            if updated_agent_system_prompts == old_system_prompts and (
                                tool_ids_to_add or tool_ids_to_remove or current_agent_description!=updated_agent_description or current_application_workflow_description!=updated_agent_workflow_description
                            ):
                                update_details["system_prompt"] = {}

                            result = requests.put(f"{ENDPOINT_URL_PREFIX}/update-agent", json=update_details, timeout=None).json()
                            st.write(result)

                        else:
                            st.write("Please enter your Email id")


        except requests.exceptions.ReadTimeout:
            st.write(f"Error: Request Timeout!")
        except ValueError:
            st.write("No Agents Available.")
        except Exception as e:
            st.write(e)

    elif action == 'Delete Agent':
        st.title("Delete Agent")
        st.markdown("<br>", unsafe_allow_html=True)

        try:
            dfs = select_agent()
            selected_agents = dfs[0]
            st.write("Select the Agents you want to delete")

            # Extract the IDs of selected agents
            selected_id = selected_agents['agentic_application_id'].tolist()
            if len(selected_id) > 1:
                st.write('You can only select 1 agent at a time')
            elif len(selected_id) == 0:
                st.write('Please select one agent')
            else:
                email = st.text_input('Enter email:')
                if st.button('Delete'):
                    if email:
                        details = {
                            "agentic_application_id": selected_id[0],
                            "user_email_id": email
                        }

                        response = requests.delete(
                            f"{ENDPOINT_URL_PREFIX}/delete-agent/{selected_id[0]}", json=details, timeout=None).json()
                        st.write(response)
                        st.write('Updated Agents:')
                        new_agent_list = display_agents()
                        st.write(new_agent_list)
                    else:
                        st.write("Please enter email")

        except requests.exceptions.ReadTimeout:
            st.write(f"Error: Request Timeout!")
        except ValueError:
            st.write("No Agents Available.")
        except Exception as e:
            st.write(e)




# Inference

def render_chat(chat_box):
    """
    Renders the chat messages in the chat box.

    Iterates over the chat history stored in `st.session_state['chat_history']['executor_messages']`
    and displays each message, differentiating between user and assistant messages.
    """

    with chat_box.container():
        executor_messages = st.session_state['chat_history'].get("executor_messages", [])
        for i, chat in enumerate(executor_messages):
            if "error" in chat:
                st.write(chat)
                return

            user_message = chat["user_query"]
            final_response = chat["final_response"] if "final_response" in chat else None
            agent_steps = chat["agent_steps"] if "agent_steps" in chat else None

            with st.chat_message("human"):
                st.markdown(f"<div class='user-message'>{user_message}</div>", unsafe_allow_html=True)

            payload = {
                "agentic_application_id": st.session_state["agent_id"],
                "session_id": st.session_state['session_id'],
                "model_name": st.session_state["model_name"],
                "query": chat["user_query"],
                "reset_conversation": False
            }

            if final_response:
                with st.chat_message("ai"):
                    st.markdown(f"<div class='assistant-message'>{final_response}</div>", unsafe_allow_html=True)

                    if st.session_state.get("selected_agent_type", None) == "React Agent" and i == len(executor_messages)-1:
                        if not st.session_state.is_last_response_disliked:
                            cols = st.columns([0.1,1,1,1,7])
                            with cols[1]:
                                if st.button("👍", key=f"like_{i}"):
                                    response = requests.post(f"{ENDPOINT_URL_PREFIX}/react-agent/get-feedback-response/like", json=payload, timeout=None).json()
                                    st.toast(response.get("message", "Couldn't fetch the response"), icon=("✅" if "message" in response else "❌"))
                            with cols[2]:
                                if st.button("👎", key=f"dislike_{i}"):
                                    st.session_state.is_last_response_disliked = True
                                    st.rerun()
                            with cols[3]:
                                if st.button("🔄", key=f"regenerate_{i}"):
                                    response = requests.post(f"{ENDPOINT_URL_PREFIX}/react-agent/get-feedback-response/regenerate", json=payload, timeout=None).json()
                                    st.session_state["chat_history"] = response
                                    st.rerun()
                        if st.session_state.is_last_response_disliked:
                            st.warning("I apologize for the previous response. Could you please provide more details on what went wrong? Your feedback will help us improve.")
                            query = st.chat_input("Enter your feedback:")
                            if query:
                                payload["query"] = query
                                response = requests.post(f"{ENDPOINT_URL_PREFIX}/react-agent/get-feedback-response/feedback", json=payload, timeout=None).json()
                                st.session_state["chat_history"] = response
                                st.session_state.is_last_response_disliked = False
                                st.rerun()


                    if agent_steps:
                        with st.expander("Steps"):
                            # st.text(agent_steps)
                            st.text(agent_steps.replace("\\n","\n"))

            elif st.session_state['chat_history'].get("current_query_status", None) == "plan":
                with st.expander("Plan", expanded=True):
                    for plan_step in st.session_state['chat_history'].get('plan', []):
                        st.info(plan_step)
                    col_feedback = st.columns([0.1,4])
                    with col_feedback[1]:
                        plan_approved = st.feedback('thumbs', key="thumbs_feedback")
                        if plan_approved != None:
                            st.session_state.pop("thumbs_feedback", None)
                            payload["approval"] = "yes" if plan_approved else "no"
                            try:
                                response = {}
                                if st.session_state.selected_agent_type == "Planner Executor Agent":
                                    response = requests.post(
                                        f"{ENDPOINT_URL_PREFIX}/planner-executor-agent/get-query-response-hitl-replanner",
                                        json=payload,
                                        timeout=None).json()
                                elif st.session_state.selected_agent_type == "Multi Agent":
                                    response = requests.post(
                                            f"{ENDPOINT_URL_PREFIX}/planner-executor-critic-agent/get-query-response-hitl-replanner",
                                            json=payload,
                                            timeout=None).json()
                                st.session_state['chat_history'] = response
                                st.rerun()
                            except Exception as e:
                                st.write(f"Error:\n{e}")

            elif st.session_state['chat_history'].get("current_query_status", None) == "feedback":
                with st.expander("Plan", expanded=True):
                    for plan_step in st.session_state['chat_history'].get('plan', []):
                        st.info(plan_step)
                    st.warning("I apologize for the previous plan not being up to the mark. Could you please provide more details on what went wrong? Your feedback will help us improve.")
                    plan_feedback = st.chat_input("Enter your feedback:")
                    try:
                        if plan_feedback:
                            payload['approval'] = "no"
                            payload['feedback'] = plan_feedback
                            response = {}
                            if st.session_state.selected_agent_type == "Planner Executor Agent":
                                response = requests.post(
                                    f"{ENDPOINT_URL_PREFIX}/planner-executor-agent/get-query-response-hitl-replanner",
                                    json=payload,
                                    timeout=None).json()
                            elif st.session_state.selected_agent_type == "Multi Agent":
                                response = requests.post(
                                    f"{ENDPOINT_URL_PREFIX}/planner-executor-critic-agent/get-query-response-hitl-replanner",
                                    json=payload,
                                    timeout=None).json()
                            st.session_state['chat_history'] = response

                            st.rerun()
                    except Exception as e:
                        st.write(f"Error:\n{e}")



def inference():
    """
    Handles the inference process by allowing users to interact with an AI agent.

    Displays a UI for selecting an agent and model, then retrieves the agent's chat history
    and displays it. Users can send messages to the agent, and the function sends the query
    to the backend for a response. Both user and assistant messages are displayed in a styled
    chat interface, with the option to view the steps of the agent's responses.

    Returns:
        None
    """
    st.title("Inference")
    try:
        st.session_state['session_id'] = 'user@example.com_1234'

        agents_df = display_agents()
        agents_df['tags'] = agents_df['tags'].apply(lambda x: str([tag['tag_name'] for tag in x]))
        cols = st.columns([2.8, 0.1, 5, 0.7, 2.6])
        with cols[0]:
            try:
                available_tags = requests.get(f"{ENDPOINT_URL_PREFIX}/tags/get-available-tags", timeout=None).json()
                available_tags = [tag['tag_name'] for tag in available_tags]
            except:
                available_tags = []

            agentic_application_types = agents_df["agentic_application_type"].unique().tolist()
            agentic_application_types = list(map(lambda x: x.replace("_", " ").title(), agentic_application_types))
            all_options = ["---AGENT TYPE---"] + agentic_application_types + ["--------TAGS--------"] + available_tags
            select_agent_filter = st.selectbox("Select Agent Filter", all_options, index=1)
            if select_agent_filter.startswith("--") and select_agent_filter.endswith("--"):
                with cols[2]:
                    st.warning(f'Select a Valid {select_agent_filter.replace("-", "")}')
                return

            if select_agent_filter in agentic_application_types:
                selected_agent_type = select_agent_filter
                selected_agent_tag = ""
            elif select_agent_filter in available_tags:
                selected_agent_type = ""
                selected_agent_tag = select_agent_filter


        with cols[2]:
            if selected_agent_type:
                list_of_agents = agents_df[agents_df["agentic_application_type"] == selected_agent_type.lower().replace(" ", "_")
                                           ]['agentic_application_name'].tolist()
            elif selected_agent_tag:
                list_of_agents = agents_df[agents_df['tags'].apply(lambda x: selected_agent_tag in ast.literal_eval(x))
                                           ]['agentic_application_name'].tolist()
            if not list_of_agents:
                st.info("No agent Available for selected filter")
                return
            sel_agent_name = st.selectbox('Select an agent', list_of_agents)
            selected_agent_df_row = agents_df[agents_df['agentic_application_name']== sel_agent_name]
            st.session_state["selected_agent_type"] = selected_agent_type = selected_agent_df_row["agentic_application_type"].iloc[0].replace("_", " ").title()
            agent_id = selected_agent_df_row['agentic_application_id'].iloc[0]
            st.session_state['agent_id'] = agent_id

        with cols[4]:
            model_name = st.selectbox("Model Name:",
                                    options=model_options,
                                    index=(0 if "gpt-4o" not in model_options else model_options.index("gpt-4o")),
                                    placeholder="--Select--",
                                    help="Choose the AI model for your agent")
            st.session_state['model_name'] = model_name


        payload = {
            "session_id": st.session_state['session_id'],
            "agent_id": agent_id,
        }
        response = requests.post(f"{ENDPOINT_URL_PREFIX}/get-chat-history", json=payload, timeout=None).json()
        if st.session_state.setdefault("reset_chat", None) is None:
            st.session_state['chat_history'] = response
        col_1, col_2, col_3=st.columns([1,1,0.25])
        st.session_state.hitl_toggle = False


        with col_1:
            if st.button("Inference"):
                if not agent_id or not model_name:
                    st.error("Please enter the agent ID and model name.")
                    return

                # st.session_state['session_id'] = 'test_101'
                st.session_state.is_last_response_disliked = False
                payload = {
                    "session_id": st.session_state['session_id'],
                    "agent_id": agent_id
                }

                response = requests.post(f"{ENDPOINT_URL_PREFIX}/get-chat-history", json=payload, timeout=None).json()

                if st.session_state.setdefault("reset_chat", None) is None:
                    st.session_state['chat_history'] = response
                st.session_state['Inference_clicked'] = True
        with col_3:
            if selected_agent_type == "Multi Agent" or selected_agent_type == "Planner Executor Agent":
                st.session_state.hitl_toggle = st.toggle(" ",
                            key="hitl_toggle_button",
                            help="Human in the Loop (Verify Plan)."
                        )


        if st.session_state.get('Inference_clicked', False):
            # Create a container for the chat box
            chat_box = st.empty()


            # Display chat messages
            render_chat(chat_box)
            # Chat input
            message = st.chat_input("Enter your message:", disabled=st.session_state.is_last_response_disliked)

            if message:
                # Add user message to chat history
                if "executor_messages" not in st.session_state['chat_history']:
                    st.session_state['chat_history']['executor_messages'] = []
                st.session_state['chat_history']['executor_messages'].append({'user_query': message})

                # Re-render chat messages
                render_chat(chat_box)
                if st.session_state.setdefault("reset_chat", None):
                    reset_chat = True
                else:
                    reset_chat = False
                # Perform inference
                inputs = {
                    "agentic_application_id": agent_id,
                    "query": message,
                    "session_id": st.session_state['session_id'],
                    "model_name": model_name,
                    "reset_conversation": reset_chat
                }

                if st.session_state.setdefault("reset_chat", None):
                    st.session_state.pop("reset_chat")

                try:
                    if selected_agent_type == "Meta Agent":
                        response = requests.post(
                            f"{ENDPOINT_URL_PREFIX}/meta-agent/get-query-response", json=inputs).json()
                    elif selected_agent_type == "Planner Meta Agent":
                        response = requests.post(
                            f"{ENDPOINT_URL_PREFIX}/planner-meta-agent/get-query-response", json=inputs).json()
                    elif selected_agent_type == "Multi Agent" and st.session_state.hitl_toggle:
                        response = requests.post(
                            f"{ENDPOINT_URL_PREFIX}/planner-executor-critic-agent/get-query-response-hitl-replanner", json=inputs).json()
                    elif selected_agent_type == "Planner Executor Agent" and st.session_state.hitl_toggle:
                        response = requests.post(
                            f"{ENDPOINT_URL_PREFIX}/planner-executor-agent/get-query-response-hitl-replanner", json=inputs).json()
                    else:
                        response = requests.post(
                            f"{ENDPOINT_URL_PREFIX}/get-query-response", json=inputs, timeout=None).json()
                    st.session_state['chat_history'] = response
                    st.rerun()
                except Exception as e:
                    st.write(f"Error: {e}")

                st.write(response)


                # Re-render chat messages

            if st.button('Reset Chat'):
                if st.session_state.setdefault("reset_chat", None) is None:
                    st.session_state["reset_chat"] = True
                    st.session_state['chat_history'] = {}
                    # Re-render chat messages
                    chat_box.empty()
                    st.rerun()

    except requests.exceptions.ReadTimeout:
        st.write(f"Error: Request Timeout!")
        return
    except ValueError:
        st.write("No Agents Available.")
        return
    except Exception as e:
        st.write(e)
        return



# Function to save uploaded files using FastAPI
def upload_files_to_fastapi(uploaded_files, subdirectory=""):
    for uploaded_file in uploaded_files:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        response = requests.post(f"{ENDPOINT_URL_PREFIX}/files/user-uploads/upload-file/", files=files, params={"subdirectory": subdirectory})
        if response.status_code == 200:
            st.success(f"File '{uploaded_file.name}' uploaded successfully.", icon='✅')
        else:
            st.error(f"Failed to upload file '{uploaded_file.name}'.")

# Function to get file structure from FastAPI
def get_file_structure_from_fastapi():
    response = requests.get(f"{ENDPOINT_URL_PREFIX}/files/user-uploads/get-file-structure/")
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Failed to retrieve file structure.")
        return {}

# Function to delete a file using FastAPI
def delete_file_from_fastapi(file_path):
    response = requests.delete(f"{ENDPOINT_URL_PREFIX}/files/user-uploads/delete-file/", params={"file_path": file_path})
    if response.status_code == 200:
        st.success(f"File '{file_path}' deleted successfully.")
    else:
        st.error(response.json().get("detail", "Failed to delete file."))

def file_uploading_ui():
    st.header("File Upload and Management")

    # Display contents of the base directory
    file_structure = get_file_structure_from_fastapi()
    with st.popover("View Files"):
        st.info(f"Contents of user_uploads folder:")
        st.write(file_structure)

    upload_file_tab, delete_file_tab = st.tabs(["Upload Files", "Delete Files"])

    with upload_file_tab:
        with st.form("Upload Files"):
            st.markdown("<br>", unsafe_allow_html=True)

            # Allow user to select or create a subdirectory
            subdirectory = st.text_input("Enter subdirectory name (leave blank for base directory):")

            st.markdown("<br>", unsafe_allow_html=True)

            # File uploader
            uploaded_files = st.file_uploader("Choose files", accept_multiple_files=True)

            # Upload button
            if st.form_submit_button("Upload Files"):
                if uploaded_files:
                    upload_files_to_fastapi(uploaded_files, subdirectory)
                else:
                    st.warning("No files selected for upload.")

    with delete_file_tab:
        with st.form("Delete File"):
            st.markdown("<br>", unsafe_allow_html=True)

            # Input field for the user to enter the path to delete
            delete_path = st.text_input("Enter the path to delete (e.g., python/files/a.py):")
            st.markdown("<br>", unsafe_allow_html=True)
            delete_path_confirmation = st.text_input("Re-enter the path to delete for confirmation:")

            # Delete button
            if st.form_submit_button("Delete"):
                if not delete_path or not delete_path_confirmation:
                    st.warning("Please enter a valid path for the file in both the fields.")
                elif delete_path != delete_path_confirmation:
                    st.warning("The path entered does not match the confirmation path.")
                else:
                    delete_file_from_fastapi(delete_path)

# data connector part start
def data_connector():
    

    st.header("🧠 Natural Language to SQL Query Runner")
    step = st.selectbox("Choose Action", ["Connect to a Database", "Generate and Run Query for sql databases", "Manual CRUD Operations for mongodb" , "Active connections"])

    if step == "Connect to a Database":
        st.subheader("🔌 Connect to a Database")

        display_to_internal = {
            "MySQL": "mysql",
            "PostgreSQL": "postgresql",
            "MongoDB": "mongodb",
            # "AzureSQL": "azuresql",
            "SQLite": "sqlite"
        }

        # Default port and username mapping
        default_config = {
            "mysql": {"port": 3306, "username": "root"},
            "postgresql": {"port": 5432, "username": "postgres"},
            "mongodb": {"port": 27017, "username": "myuser"},
            # "azuresql": {"port": 1433, "username": "azureuser"},  # Adjust as needed
            "sqlite": {"port": None, "username": None}
        }

        db_display = st.selectbox("Database Type", list(display_to_internal.keys()), index=1)
        db_type = display_to_internal[db_display]
        database = ""
        uploaded_file = None  # Make it accessible outside the form

        # Retrieve default values
        defaults = default_config.get(db_type, {"port": None, "username": ""})
        default_port = defaults["port"]
        default_username = defaults["username"]

        # FORM START
        with st.form("db_connection_form"):
            name = st.text_input("Connection Name", " ")
            host = port = username = password = ""

            if db_type == "sqlite":
                st.write("Either upload an existing SQLite DB file or create a new one by entering a filename.")

                new_db_name = st.text_input("New SQLite DB Filename (with .sqlite or .db extension)", key="new_db_name")
                uploaded_file = st.file_uploader("Upload SQLite DB File", type=["sqlite", "db", "sqlite3"], key="upload_file")

                database = ""

                # Validation: make sure only one option is chosen
                if new_db_name and uploaded_file:
                    st.error("Please either upload a file or enter a new filename, not both.")
                    connect_btn = False  # disable connect button if you want
                elif new_db_name:
                    # Validate filename extension
                    if not (new_db_name.endswith(".sqlite") or new_db_name.endswith(".db")):
                        st.error("Filename should end with .sqlite or .db")
                        connect_btn = False
                    else:
                        file_path = os.path.join(UPLOAD_DIR, new_db_name)
                        # Create empty SQLite file if it doesn't exist
                        if not os.path.exists(file_path):
                            import sqlite3
                            conn = sqlite3.connect(file_path)
                            conn.close()
                            st.info(f"New SQLite DB file created at: `{file_path}`")
                        database = file_path
                elif uploaded_file:
                    file_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    database = file_path
                    st.info(f"SQLite file saved at: `{database}`")
                else:
                    st.warning("Please upload a file or enter a new filename.")
                    connect_btn = False
            else:
                host = st.text_input("Host", value="localhost")
                if default_port:
                    port = st.number_input("Port", value=default_port, format="%d")
                else:
                    port = st.number_input("Port", format="%d")
                username = st.text_input("Username", value=default_username)
                password = st.text_input("Password", type="password")
                database = st.text_input("Database Name", "test_db")

            connect_btn = st.form_submit_button("Connect")
        # FORM END

        # Outside form: handle download and submission
        if db_type == "sqlite" and uploaded_file:
            with open(database, "rb") as f:
                st.download_button("⬇️ Download SQLite File", f, file_name=uploaded_file.name)

        if connect_btn:
            
            if db_type == "sqlite" and not database:
                st.error("❌ Please upload a valid SQLite database file.")
                return

            # if db_type == "mongodb" and not database.strip().startswith("mongodb://"):
            #     st.error("❌ Please enter a valid MongoDB URI.")
            #     return

            if db_type == "sqlite":
                port = 0
            flag="1"
            payload = {
                "name": name.strip(),
                "db_type": db_type,
                "host": host,
                "port": port,
                "username": username,
                "password": password,
                "database": database,
                "flag_for_insert_into_db_connections_table": flag
            }

            try:
                # logger.info("printing payload")
                # logger.info(payload)
                res = requests.post(f"{ENDPOINT_URL_PREFIX}/connect", json=payload)
                if res.status_code == 200:
                    st.success(res.json()["message"])
                else:
                    st.error(f"❌ {res.json().get('detail', 'Connection failed.')}")
            except Exception as e:
                st.error(f"❌ Request failed: {e}") 

        
        # logger.info("inside disconnect")
        # logger.info(name)
        try:
            response = requests.get(f"{ENDPOINT_URL_PREFIX}/connections")
            response.raise_for_status()
            connections_list = response.json().get("connections", [])
        except Exception:
            connections_list = []

        if connections_list:
            # Build a mapping from connection name to full connection info
            connection_map = {conn["connection_name"]: conn for conn in connections_list}

            selected_name = st.selectbox("Select previously Connected DB", list(connection_map.keys()))
            selected_connection = connection_map[selected_name]
            name=selected_name
            # logger.info(selected_connection)
            db_type=selected_connection["connection_database_type"]
            
            disconnect_btn = st.button("Disconnect & forget the details of the connection")
            activate_btn=st.button("activate")
            if disconnect_btn:
                if not name:
                    st.error("❌ Please enter the connection name to disconnect.")
                else:
                    payload = {
                        "name": name,
                        "db_type": db_type,
                    }
                    # logger.info(payload)
                    try:
                        res = requests.post(f"{ENDPOINT_URL_PREFIX}/disconnect", json=payload)
                        if res.status_code == 200:
                            st.success(res.json()["message"])
                        else:
                            st.error(f"❌ {res.json().get('detail', 'Disconnection failed.')}")
                    except Exception as e:
                        st.error(f"❌ Request failed: {e}")

            if activate_btn:
                try:
                    if selected_connection["connection_database_type"] == "sqlite":
                        port = 0

                    flag="0"
                    
                    payload = {
                        "name": selected_connection["connection_name"],
                        "db_type": selected_connection["connection_database_type"],
                        "host": selected_connection["connection_host"],
                        "port": selected_connection["connection_port"],
                        "username": selected_connection["connection_username"],
                        "password": selected_connection["connection_password"],
                        "database": selected_connection["connection_database_name"],
                        "flag_for_insert_into_db_connections_table":flag
                    }
                    # logger.info("printing payload")
                    # logger.info(payload)
                    res = requests.post(f"{ENDPOINT_URL_PREFIX}/connect", json=payload)
                    if res.status_code == 200:
                        st.success(res.json()["message"])
                    else:
                        st.error(f"❌ {res.json().get('detail', 'Connection failed.')}")
                except Exception as e:
                    st.error(f"❌ Request failed: {e}")


    # --- Step 2: Generate and Run Query ---
    elif step == "Generate and Run Query for sql databases":
        try:
            response = requests.get(f"{ENDPOINT_URL_PREFIX}/connections_sql")
            response.raise_for_status()
            connections_list = response.json().get("connections", [])
        except Exception:
            connections_list = []

        if connections_list:
            # Build a mapping from connection name to full connection info
            connection_map = {conn["connection_name"]: conn for conn in connections_list}

            selected_name = st.selectbox("Select Connected DB", list(connection_map.keys()))
            selected_connection = connection_map[selected_name]

            db_type = selected_connection["connection_database_type"]
            st.write(f"ℹ️ Selected DB Type: {db_type}")
            nl_query = st.text_area("Enter Natural Language Query")

            if st.button("🔍 Generate Query"):
                if not nl_query.strip():
                    st.warning("Please enter a query.")
                else:
                    with st.spinner("Generating query..."):
                        gen_payload = {
                            "database_type": db_type,
                            "natural_language_query": nl_query
                        }
                        try:
                            res = requests.post(f"{ENDPOINT_URL_PREFIX}/generate_query", json=gen_payload)
                            if res.status_code == 200:
                                generated_query = res.json()["generated_query"]
                                st.session_state.generated_query = generated_query
                                st.success("✅ Query Generated. You can review and edit it before running.")
                            else:
                                st.error(f"❌ Query generation failed: {res.json().get('detail')}")
                        except Exception as e:
                            st.error(f"❌ Failed to generate query: {e}")

            if "generated_query" in st.session_state:
                updated_query = st.text_area("🛠️ Review or Edit the Generated Query", value=st.session_state.generated_query, height=150)

                if st.button("▶ Run Query"):
                    if not updated_query.strip():
                        st.warning("Query cannot be empty.")
                    else:
                        with st.spinner("Executing query..."):
                            run_payload = {"name": selected_name, "query": updated_query}
                            try:
                                run_res = requests.post(f"{ENDPOINT_URL_PREFIX}/run_query", json=run_payload)
                                if run_res.status_code == 200:
                                    data = run_res.json()
                                    if "message" in data:
                                        st.success(data["message"])
                                    elif data["rows"]:
                                        df = pd.DataFrame(data["rows"], columns=data["columns"])
                                        st.success("✅ Query executed successfully.")
                                        st.dataframe(df)
                                    else:
                                        st.info("✅ Query ran successfully, but no rows were returned.")
                                else:
                                    st.error(f"❌ Query failed: {run_res.json().get('detail')}")
                            except Exception as e:
                                st.error(f"❌ Request failed: {e}")

        else:
            st.warning("⚠️ No connected databases. Connect to a database first.")

    # --- Step 3: Manual CRUD Operations ---
    elif step == "Manual CRUD Operations for mongodb":
        try:
            # logger.info("in manual crud")
            response = requests.get(f"{ENDPOINT_URL_PREFIX}/connections_mongodb")
            # logger.info(response)
            response.raise_for_status()
            connections_list = response.json().get("connections", [])
            # logger.info(connections_list)
        except Exception:
            connections_list = []

        if connections_list:
            # Build a map from connection_name to full connection data
            connection_map = {conn["connection_name"]: conn for conn in connections_list}

            selected_name = st.selectbox("Select Connected DB", list(connection_map.keys()))
            selected_connection = connection_map[selected_name]

     
            collection = st.text_input("Collection Name", "users")
            operation = st.selectbox("Operation", ["find", "insert", "update", "delete"])
            mode = st.selectbox("Mode", ["one", "many"])

            query_input = st.text_area("Query (JSON)", '{ "name": "Alice" }')

            data_input = ""
            if operation in ["insert"]:
                data_input = st.text_area("Data (JSON)", '{ "name": "Alice", "age": 30 }')
            elif operation == "update":
                update_input = st.text_area("Update Data (JSON)", '{ "age": 31 }')

            if st.button("Execute"):
                try:
                    query = json.loads(query_input) if query_input else {}
                    data = json.loads(data_input) if data_input else None
                    update_data = json.loads(update_input) if operation == "update" else None

                    payload = {
                        "conn_name": selected_name,
                        "collection": collection,
                        "operation": operation,
                        "mode": mode,
                        "query": query,
                        "data": data,
                        "update_data": update_data
                    }
                    # logger.info(payload)
                    # logger.info(crud_connection)

                    with st.spinner("Executing..."):
                        response = httpx.post(f"{ENDPOINT_URL_PREFIX}/mongodb-operation/", json=payload)
                        response.raise_for_status()
                        result = response.json()

                    st.success("Operation successful!")
                    st.json(result)

                except Exception as e:
                    st.error(f"Error: {e}")

    elif step == "Active connections":
        st.title("Active Connections Dashboard")
        if st.button("Show Active Connections"):
            try:
                response = requests.get(f"{ENDPOINT_URL_PREFIX}/get-active-connection-names")
                response.raise_for_status()
                data = response.json()
                
                st.subheader("Active SQL Connections")
                if data["active_sql_connections"]:
                    for conn in data["active_sql_connections"]:
                        st.write(f"- {conn}")
                else:
                    st.write("No active SQL connections.")
                
                st.subheader("Active Mongo Connections")
                if data["active_mongo_connections"]:
                    for conn in data["active_mongo_connections"]:
                        st.write(f"- {conn}")
                else:
                    st.write("No active Mongo connections.")
            except Exception as e:
                st.error(f"Failed to fetch active connections: {e}")

        # # Placeholder for your logic
        # st.title("Activate a previous connection")

        # # Step 1: Fetch connections when button is clicked
        # if st.button("Fetch Connections"):
        #     try:
        #         response = requests.get(f"{ENDPOINT_URL_PREFIX}/connections")
        #         response.raise_for_status()
        #         connections = response.json().get("connections", [])
        #     except Exception as e:
        #         st.error(f"Failed to fetch connections: {e}")
        #         connections = []
            
        #     if connections:
        #         connection_map = {conn["connection_name"]: conn for conn in connections}
        #         selected_name = st.selectbox("Select a connection", list(connection_map.keys()))
                
        #         selected_conn = connection_map[selected_name]
        #         db_type = selected_conn["connection_database_type"]
                
        #         # Prepare payload
        #         payload = {
        #             "name": selected_conn["connection_name"],
        #             "db_type": db_type,
        #             "host": selected_conn["connection_host", ""],
        #             "port": selected_conn["connection_port", 0],
        #             "username": selected_conn["connection_username", ""],
        #             "password": selected_conn["connection_password", ""],
        #             "database": selected_conn["connection_database_name", ""]
        #         }


        #         if db_type.lower() == "sqlite":
        #             payload["host"] = "Na"
        #             payload["port"] = 0
        #             payload["username"] = "Na"
        #             payload["password"] = "Na"
                
        #         logger.info(payload)

        #         # Step 2: Button to activate selected connection
        #         if st.button("Activate Selected Connection"):
        #             try:
        #                 connect_resp = requests.post(f"{ENDPOINT_URL_PREFIX}/connect", json=payload)
        #                 connect_resp.raise_for_status()
        #                 result = connect_resp.json()
        #                 st.success(result.get("message", "Connection activated successfully."))
        #             except Exception as e:
        #                 st.error(f"Failed to activate connection: {e}")
        #     else:
        #         st.warning("No connections available.")

#dataconnector part end

# Main function
def main():
    """
    Main function for the web application that handles the user interface.

    Displays the title of the application, sets up a sidebar with navigation options,
    and directs the user to different functionalities based on their selection:
    - "Tool Onboard": Calls the `onboard_tool()` function.
    - "Agent Onboard": Calls the `define_agent()` function.
    - "Inference": Calls the `inference()` function.

    Returns:
        None
    """
    set_global_styles()

    st.markdown("<h1 style='text-align: center;'>Agentic Workflow As Service</h1>",
                unsafe_allow_html=True)

    # Sidebar styling
    with st.sidebar:
        st.markdown(
            "<h3 style='text-align: center; padding: 1rem 0;'>Navigation</h3>", unsafe_allow_html=True)
        selected_tab = st.radio(
            label="Navigation Option",
            options=["Tool Onboard", "Agent Onboard", "Inference", "Upload Documents","Data Connector"],
            label_visibility="hidden")

    if selected_tab == "Tool Onboard":
        onboard_tool()

    elif selected_tab == "Agent Onboard":
        define_agent()

    elif selected_tab == "Inference":
        inference()

    elif selected_tab == "Upload Documents":
        file_uploading_ui()

    elif selected_tab == "Data Connector":
        data_connector()
    # elif selected_tab == "Previous Chats":
    #     old_chats()



if __name__ == "__main__":
    main()
