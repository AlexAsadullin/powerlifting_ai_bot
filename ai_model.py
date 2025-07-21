import re
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import logging
import PyPDF2
from database import Session
from models import KnowledgeBase
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Установка устройства
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info(f"Using device: {device}")

model_name = "Soorya03/Llama-3.2-1B-Instruct-FitnessAssistant"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True
)
logger.info(f"Loaded model: {model_name}")


def clean_response(response):
    # Удаляем все слова, соответствующие маске "</*>"
    cleaned_response = re.sub(r'</[^>]+>', '', response)
    # Удаляем лишние пробелы и возвращаем результат
    return cleaned_response.strip()


def get_token_count(text):
    """
    Возвращает количество токенов в тексте.
    """
    return len(tokenizer.encode(text))


def truncate_to_token_limit(text, token_limit):
    """
    Обрезает текст до указанного количества токенов.
    """
    tokens = tokenizer.encode(text, add_special_tokens=False)
    if len(tokens) > token_limit:
        tokens = tokens[:token_limit]
    return tokenizer.decode(tokens, clean_up_tokenization_spaces=True)


def get_knowledge_base_summary(word_limit=1000):
    """
    Возвращает сокращенную версию базы знаний, извлекая текст из PDF и TXT файлов, игнорируя изображения.
    """
    logger.info("Starting to generate knowledge base summary")
    session = Session()
    try:
        materials = session.query(KnowledgeBase).all()
        summary = ""
        for material in materials:
            if material.type == 'text' and material.content:
                summary += material.content + "\n"
            elif material.type == 'file' and material.file_path:
                if material.file_path.endswith('.pdf'):
                    try:
                        with open(material.file_path, 'rb') as f:
                            reader = PyPDF2.PdfReader(f)
                            text = ""
                            for page in reader.pages:
                                page_text = page.extract_text() or ""
                                text += page_text + "\n"
                            summary += text + "\n"
                    except Exception as e:
                        logger.warning(f"Failed to read PDF {material.file_path}: {str(e)}")
                elif material.file_path.endswith('.txt'):
                    try:
                        with open(material.file_path, 'r', encoding='utf-8') as f:
                            text = f.read()
                            summary += text + "\n"
                    except Exception as e:
                        logger.warning(f"Failed to read TXT {material.file_path}: {str(e)}")
            elif material.type == 'file' and material.text_content:
                summary += material.text_content + "\n"
        words = summary.split()
        if len(words) > word_limit:
            summary = " ".join(words[:word_limit]) + "..."
        logger.info(f"Generated knowledge base summary with {len(words)} words")
        return summary
    except Exception as e:
        logger.error(f"Error generating knowledge base summary: {str(e)}")
        return "Knowledge base unavailable."
    finally:
        session.close()


def generate_response(training_entries="", nutrition_entries="", knowledge_base="", user_query="", max_tokens=2 ** 13):
    """
    Генерирует ответ на основе предоставленных данных, приоритизируя историю тренировок,
    затем питание, затем базу знаний, с учетом лимита токенов. Запросы и ответы на английском.

    Args:
        training_entries (str): История тренировок в виде строки.
        nutrition_entries (str): История питания в виде строки.
        knowledge_base (str): База знаний в виде строки.
        user_query (str): Запрос пользователя на английском.
        max_tokens (int): Максимальное количество токенов для промпта.

    Returns:
        str: Сгенерированный ответ на английском языке или сообщение об ошибке.
    """
    logger.info("Starting response generation")
    try:
        # Базовая инструкция на английском
        base_instruction = "topic: Powerlifting fitness for teenagers.\n"

        # Формируем промпт с четким разделением контекста и запроса
        prompt = f"""Context:
        {base_instruction}
        Training history: {training_entries}
        Nutrition history: {nutrition_entries}
        Knowledge base: {knowledge_base}

        User query: {user_query}

        Assistant:"""

        # Токенизация промпта
        inputs = tokenizer(prompt, return_tensors='pt', padding=True, truncation=True, max_length=max_tokens)
        input_ids = inputs['input_ids'].to(device)
        attention_mask = inputs['attention_mask'].to(device)
        logger.info(f"Input tokenized: {input_ids.shape}, prompt length: {len(prompt)}")

        # Генерация ответа
        output = model.generate(
            input_ids,
            attention_mask=attention_mask,
            max_new_tokens=100,
            do_sample=True,
            temperature=0.5,
            pad_token_id=tokenizer.eos_token_id
        )
        logger.info(f"Generated output shape: {output.shape}")

        # Извлекаем только сгенерированные токены
        input_length = input_ids.size(1)
        generated_ids = output[0][input_length:]
        response = tokenizer.decode(generated_ids, skip_special_tokens=True)
        logger.info(f"Decoded response length: {len(response)}")

        # Очищаем ответ от лишних пробелов
        response = response.strip()
        return clean_response(response)
    except Exception as e:
        logger.error(f"Error during response generation: {str(e)}")
        return f"Error generating response: {str(e)}"
