from tools.llm_utils import langsmith_status, ping_gemini


def main() -> None:
    print("[LangSmith Status]", langsmith_status())

    response = ping_gemini("You are a connectivity checker. Reply with exactly: CONNECTED")
    text = getattr(response, "content", str(response))
    print("[Gemini Response]", text)


if __name__ == "__main__":
    main()
