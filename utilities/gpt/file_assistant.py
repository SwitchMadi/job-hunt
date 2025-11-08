import os
import dotenv
from openai import OpenAI
import yaml

from utilities.logging import get_logger

dotenv.load_dotenv()
logger = get_logger(name="gpt")
client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
config = yaml.safe_load(open("config.yml"))


def get_file_assistant(name, instructions):
    assistant = client.beta.assistants.create(
        name=name,
        instructions=instructions,
        model=config["openai_models"]["complex"],
        tools=[{"type": "file_search"}],
    )

    return assistant


def get_vector_store(name, files):
    vector_store = client.beta.vector_stores.create(name=name)

    file_streams = [open(path, "rb") for path in files]

    # Use the upload and poll SDK helper to upload the files, add them to the vector store,
    # and poll the status of the file batch for completion.
    file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
        vector_store_id=vector_store.id, files=file_streams
    )

    # You can print the status and the file counts of the batch to see the result of this operation.
    logger.info(f"file_batch status - {file_batch.status}")
    logger.info(f"file_batch files count - {file_batch.file_counts}")

    return vector_store


def query_file(query, file):
    assistant = get_file_assistant(
        name="Resume parser assistant",
        instructions="You are a resume parser assistant. Use you knowledge base to extract information from the resume.",
    )
    vector_store = get_vector_store(name="Resume", files=[file])

    assistant = client.beta.assistants.update(
        assistant_id=assistant.id,
        tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
    )

    # Create a thread and attach the file to the message
    thread = client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": query,
            }
        ]
    )

    # Use the create and poll SDK helper to create a run and poll the status of
    # the run until it's in a terminal state.
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id, assistant_id=assistant.id
    )

    messages = list(
        client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id)
    )

    message_content = messages[0].content[0].text
    annotations = message_content.annotations
    citations = []
    for index, annotation in enumerate(annotations):
        message_content.value = message_content.value.replace(
            annotation.text, f"[{index}]"
        )
        if file_citation := getattr(annotation, "file_citation", None):
            cited_file = client.files.retrieve(file_citation.file_id)
            citations.append(f"[{index}] {cited_file.filename}")

    return message_content.value
