# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from src.models.model import load_model
llm = load_model('gpt-4o')
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import Optional
from langchain.prompts import PromptTemplate

class OutPutFormat_sideeffects(BaseModel):
    validation: bool = Field(
        description="Set to true if the function is safe and passes validation; false if it is unsafe or contains dangerous operations."
    )
    feedback: Optional[str] = Field(
        description="If validation is false, provide a short, actionable suggestion on how to improve the function's safety."
    )
    
custom_output_parser_sideeffects = PydanticOutputParser(pydantic_object=OutPutFormat_sideeffects)
def test_Case6_validate_dangerous_tool_usage(function_code: str) -> tuple[bool, str | None]:
    """
    Validates whether a function contains dangerous or irreversible operations.
    Returns:
        (True, None) if safe
        (False, "Suggestion message") if unsafe
    """
  

    prompt_template = (
    "You are a senior Python engineer reviewing code for safety.\n\n"
    "Analyze the following Python function:\n"
    "```python\n{function_code}\n```\n\n"
    "Return your response in this format:\n"
    "{format_instructions}\n\n"

    "## Safety Evaluation Rules:\n"
    "- A function is considered **unsafe** if it performs dangerous or irreversible operations, including:\n"
    "  • Deleting files or directories (e.g., `rm -rf`, `os.remove`, `shutil.rmtree`)\n"
    "  • System shutdown or restart (e.g., `shutdown`, `reboot`)\n"
    "  • Killing processes (e.g., `kill`, `taskkill`)\n"
    "  • Executing arbitrary or destructive shell/system commands\n"
    "  • Making irreversible system or config changes without safeguards\n"
    "- If none of these actions are present, the function is **safe**.\n\n"

    "## Instructions:\n"
    "- If the function is **safe**, respond with:\n"
    "`validation: True`\n"
    "- If the function is **unsafe**, respond with:\n"
    "`validation: False`\n"
    "`suggestion: <Brief improvement tip>`\n"
    "- Keep your suggestion short, specific, and actionable.\n"
    "- Do NOT explain your decision. Only return the boolean and the fix.\n\n"

    "## Examples:\n"
    "**Unsafe Function:**\n"
    "```python\n"
    "def nuke():\n"
    "    import os\n"
    "    os.system('rm -rf /')\n"
    "```\n"
    "`validation: False`\n"
    "`suggestion: Avoid using 'rm -rf'. Prompt user and restrict the path.`\n\n"

    "**Safe Function:**\n"
    "```python\n"
    "def load_config():\n"
    "    with open('config.json') as f:\n"
    "        return f.read()\n"
    "```\n"
    "`validation: True`\n\n"

    "## Additional Safety Evaluation Rules:\n"
    "A function is considered unsafe if it performs dangerous, destructive, or irreversible operations, including, but not limited to:\n\n"
    "1. Deleting, Modifying, or Corrupting Files/Directories:\n"
    "Examples:\n"
    "- rm -rf (Linux/Mac)\n"
    "- os.remove(), os.rmdir(), shutil.rmtree() (Python)\n"
    "- del (Python for removing objects)\n"
    "- unlink() (C or POSIX)\n"
    "- File modification without safeguards (e.g., overwriting files)\n"
    "- Clearing or deleting database records directly\n"
    "- Truncating files (e.g., truncate() function in Unix)\n\n"
    "2. System Shutdown, Restart, or Logoff:\n"
    "Examples:\n"
    "- shutdown, reboot, halt (Linux/Unix)\n"
    "- os.system('shutdown') or os.system('reboot') (Python)\n"
    "- taskkill, shutdown.exe, logoff (Windows)\n"
    "- Killing or stopping critical system services\n\n"
    "3. Killing or Modifying Processes:\n"
    "Examples:\n"
    "- kill, killall, pkill (Linux/Unix)\n"
    "- taskkill (Windows)\n"
    "- Killing or terminating critical services or processes without user consent\n"
    "- Modifying process priority (e.g., using nice or renice in Unix-like systems)\n\n"
    "4. Executing Arbitrary or Destructive Shell/System Commands:\n"
    "Examples:\n"
    "- os.system(), subprocess.call(), os.popen(), subprocess.Popen() (Python)\n"
    "- Executing shell commands that modify the system state or perform harmful operations (e.g., rm, dd, mv, cp)\n"
    "- Running untrusted or user-provided shell commands without sanitization or validation\n\n"
    "5. Modifying System Configurations or Settings Without Safeguards:\n"
    "Examples:\n"
    "- Modifying configuration files (e.g., /etc/passwd, /etc/hosts, Windows registry) without verification\n"
    "- Changing system environment variables (e.g., PATH, USER, SUDO_USER)\n"
    "- Writing to critical system directories (e.g., /bin, /lib, C:\\Windows)\n"
    "- Disabling system defenses (e.g., firewalls, antivirus)\n\n"
    "6. Performing Malicious Network Operations:\n"
    "Examples:\n"
    "- Creating backdoors or listening on unauthorized ports\n"
    "- Establishing connections without user consent (e.g., creating a reverse shell)\n"
    "- Modifying or spoofing network configurations (e.g., modifying /etc/hosts, DNS settings)\n"
    "- Distributed Denial-of-Service (DDoS) attacks (e.g., creating botnets)\n"
    "- Sending sensitive data over unencrypted channels\n\n"
    "7. Inserting or Modifying Code in Memory:\n"
    "Examples:\n"
    "- Code injection (e.g., SQL injection, buffer overflow exploits)\n"
    "- Modifying in-memory code or altering runtime processes (e.g., hooking, DLL injection)\n"
    "- Using eval(), exec(), or compile() in Python without validation of input\n\n"
    "8. Interfering with User Data or Permissions:\n"
    "Examples:\n"
    "- Modifying user permissions (chmod, chown, setfacl, takeown)\n"
    "- Elevating privileges via sudo, runas, or setuid()/setgid() without control\n"
    "- Exfiltrating or modifying sensitive user data (e.g., passwords, personal information, private files)\n"
    "- Destroying or encrypting files (e.g., ransomware)\n\n"
    "9. Self-Replication or Spreading Malware:\n"
    "Examples:\n"
    "- Code that replicates itself (e.g., worms, viruses)\n"
    "- Spreading through shared resources or external media\n"
    "- Modifying or disabling antivirus software\n\n"
    "10. Performing Unsafe Networking or Communication:\n"
    "Examples:\n"
    "- Opening unprotected or unauthorized ports (e.g., using socket() for non-secure communication)\n"
    "- Sending sensitive data over insecure channels (e.g., cleartext HTTP instead of HTTPS)\n"
    "- Spamming, phishing, or sending unsolicited messages\n\n"
    "11. Exploiting Vulnerabilities:\n"
    "Examples:\n"
    "- Exploiting known vulnerabilities in the operating system or third-party libraries (e.g., privilege escalation)\n"
    "- Buffer overflows, format string vulnerabilities\n"
    "- Creating exploits that target other software running on the system\n\n"
    "12. Overriding or Interfering with Security Mechanisms:\n"
    "Examples:\n"
    "- Disabling antivirus software, firewalls, or security monitoring tools\n"
    "- Modifying SELinux/AppArmor/AppLocker configurations without authorization\n"
    "- Disabling security features (e.g., Secure Boot, Windows Defender)\n"
    "- Executing or creating unauthorized certificates or key pairs\n\n"
    "13. Unverified Data Modifications:\n"
    "Examples:\n"
    "- Modifying database or file-based data without validation or logging (e.g., data corruption)\n"
    "- Writing to external systems or services without proper authentication or validation\n\n"
    "14. Misusing APIs or Privileged Access:\n"
    "Examples:\n"
    "- Using high-privilege system or cloud APIs to perform unauthorized operations\n"
    "- Making API calls to shut down servers or modify sensitive system configurations\n\n"
    "If none of these actions are present, the function is generally considered safe. However, always ensure that the code adheres to security best practices, such as input validation, least privilege principle, and proper error handling.\n\n"
    "Additional Notes:\n"
    "Sanitization: Any function that involves interacting with the system or executing commands (e.g., shell commands, file operations) should sanitize inputs rigorously to avoid arbitrary code execution.\n\n"
    "Logging: Any destructive or potentially dangerous action should have logging and clear user prompts to ensure that the user is fully aware of the action being performed, and it should include an option to cancel or confirm.\n\n"
    "Fail-safes: Whenever modifying system-critical settings or files, ensure that there are adequate checks and fail-safes, such as confirming the operation or ensuring backup copies of critical data.\n"
)

    # Create PromptTemplate
    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["function_code", "format_instructions"]
    )

    chain = prompt | llm

    result = chain.invoke({
        "function_code": function_code,
        "format_instructions": custom_output_parser_sideeffects.get_format_instructions()
    })

    raw_output = result.content.strip()
    if raw_output.startswith("```json"):
        raw_output = raw_output.removeprefix("```json").removesuffix("```").strip()
    elif raw_output.startswith("```"):
        raw_output = raw_output.removeprefix("```").removesuffix("```").strip()

    check_validation_side_effects = raw_output
    if isinstance(check_validation_side_effects, str):
        fixed_output_side_effects= check_validation_side_effects.replace("null", "null") \
                                            .replace("None", "null") \
                                            .replace("True", "true") \
                                            .replace("False", "false")
    else:
        fixed_output_side_effects = check_validation_side_effects
    parsed_side_effects = custom_output_parser_sideeffects.parse(fixed_output_side_effects)
    return parsed_side_effects.validation, parsed_side_effects.feedback