import asyncio
from app import llm_client as llm


async def main():
    if not llm.available():
        print("No model configured. Check LLM_PROVIDER, LLM_API_KEY and LLM_MODEL in Backend/.env")
        return
    print("using:", llm.describe())

    print(await llm.chat([{"role": "user", "content": "Reply with exactly one word: ready"}], max_tokens=300))

    data = await llm.ask_json(
        'Extract skills. Reply with JSON like {"skills": ["..."]}.',
        "<resume>Built FastAPI services in Python with PostgreSQL and Docker.</resume>")
    print(data)

asyncio.run(main())