import os

OUTPUT_FILE = 'project_bundle.txt'
EXCLUDE_DIRS = {'venv', '__pycache__', '.git', 'media', 'staticfiles'}
EXCLUDE_EXTENSIONS = {'.pyc', '.sqlite3'}

with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
  for root, dirs, files in os.walk('.'):
    # Modify dirs in-place to skip excluded directories
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

    for file in files:
      if any(file.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
        continue

      file_path = os.path.join(root, file)
      outfile.write(f'--- FILE: {file_path} ---\n')
      try:
        with open(file_path, 'r', encoding='utf-8') as infile:
          outfile.write(infile.read())
      except Exception as e:
        outfile.write(f'[Error reading file: {e}]')
      outfile.write('\n\n' + '=' * 50 + '\n\n')

print(f'Project successfully bundled into {OUTPUT_FILE}!')