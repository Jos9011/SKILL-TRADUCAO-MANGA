# Manga Studio — Project Rules

- **Publicação automática após atualizações:** Sempre que finalizar uma nova atualização ou correção de código neste projeto, após validar sintaxe e testes necessários:
  1. Incremente a versão com `python version.py bump pequeno` (ou `medio`/`grande` quando aplicável) e mantenha `Colab_Manga_WebUI.ipynb` alinhado à versão atual.
  2. Verifique com `git status` e `git diff` que nenhuma chave de API ou arquivo `config.json` sensível será incluído.
  3. Faça `git add`, `git commit` e `git push origin main` para manter o GitHub e o Google Colab sempre atualizados.
