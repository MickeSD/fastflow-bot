import os

# Папки, которые нейросети читать не нужно (добавили .ruff_cache)
IGNORE_DIRS = {'venv', '.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'backups'}

# Расширения, которые нам важны
ALLOWED_EXTENSIONS = {'.py', '.toml', '.yml', '.yaml', '.md', '.env.example'}

# Конкретные файлы без расширений, которые тоже нужны
ALLOWED_FILES = {'Dockerfile', '.dockerignore'}

with open("full_project.txt", "w", encoding="utf-8") as outfile:
    for root, dirs, files in os.walk("."):
        # Исключаем ненужные директории
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in files:
            if any(file.endswith(ext) for ext in ALLOWED_EXTENSIONS) or file in ALLOWED_FILES:
                filepath = os.path.join(root, file)

                # Пропускаем сам скрипт и итоговый файл, чтобы не дублировать код
                if file in ["pack.py", "full_project.txt"]:
                    continue

                outfile.write(f"\n\n{'='*40}\n")
                outfile.write(f"FILE: {filepath}\n")
                outfile.write(f"{'='*40}\n\n")

                try:
                    with open(filepath, "r", encoding="utf-8") as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"<Ошибка чтения файла: {e}>\n")

print("Готово! Файл full_project.txt обновлен с учетом новой архитектуры.")
