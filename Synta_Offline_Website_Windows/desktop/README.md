# Synta
Syntax Shift | Your code. Your pace. Your AI tutor.
Education theme: Unlocking Educational Potential, Empowering Futures.

## Start on Windows 11
Install Python 3.10 or newer with Tkinter and the Python launcher, and install Ollama for Windows (https://ollama.com/download/windows). Open Ollama. Extract the ZIP. Open the folder containing codelume.py in File Explorer, type cmd in the address bar and press Enter. Run:
```cmd
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
ollama pull qwen2.5-coder:3b
.venv\Scripts\python codelume.py
```
Subsequent launches need only the last command. If you already downloaded the model, skip the pull. Close older tutors that use the same hotkeys.

## Build and test each piece
1. **Read and check.** win_editor.py reads the focused text control through Windows UI Automation. checker.py parses the snapshot locally. In an unsaved Notepad tab type the example below. With the cursor in the code press Ctrl+Alt+F8. Expect a line 1 error. Add the colon and check again before saving. Add blank lines above the code and scroll back to the top to test off-screen capture. For troubleshooting run .venv\Scripts\python codelume.py --probe and focus the Notepad editing area within five seconds.
```python
for n in [10, 20, 30]
    print(n)
```
2. **Request help.** tutor.py sends numbered code, parser result, level, expected behaviour and recent hints to Ollama on 127.0.0.1:11434/api/chat. codelume.py keeps network requests off the UI thread. Test with the following snippet. F8 with Ctrl+Alt should pass. Ctrl+Alt+F9 should ask about the types compared on line 2. For a simple text/number comparison the first clue is grounded by local source inspection. Other cases use the model's wording.
```python
score = "75"
if score >= 50:
    print("Passed")
```
3. **Control the reveal.** session.py tracks Nudge, Hint, Explain, and Show solution. Try More help one step at a time. Try What I expected to supply context. After an explanation, edit the code yourself. Use Start over for a fresh attempt.
4. **Assess.** Select Intermediate and take the diagnostic (25 questions by default). diagnostic.py holds the question bank and scoring. Open My path and check which topics your answers prioritized.
5. **Personalize.** learner.py maps topic scores to learning recommendations. Compare a Beginner explanation with an Advanced explanation of the same code after starting over. With consent, progress is saved under %APPDATA%\CodeLume. Use Forget my data to clear it.

## Customize
Change OLLAMA_MODEL in config.py or set CODELUME_MODEL to an installed local model. Edit build_input in tutor.py to adjust the context. Edit LEVEL_RULES and STAGE_RULES there to change tone and disclosure. The checked comparison clue is in comparison_clue. Edit codelume.py for the Tkinter overlay layout.

## Run the automated tests
```cmd
.venv\Scripts\python -m unittest discover -s tests -v
```
tests/test_core.py covers local checks, sessions, assessments, profiles, tutor requests and failure handling with a simulated Ollama service. Local syntax checking uses the full document. For model hints the listing is limited to 12,000 characters and marked when shortened. The local parser never executes the learner's code.
## Chat with the tutor
Open Chat with tutor to ask a general question. To discuss an unsaved Notepad tab, first press Ctrl+Alt+F8 in that tab, then open the chat. The header identifies the attached snapshot. Type a problem, expected result or example, then click Send or press Ctrl+Enter. Follow-ups include the last eight completed question/answer pairs. The conversation stays in memory. Closing the chat starts a fresh conversation next time. To discuss edited code, close chat, capture the editor again and reopen chat.

## Use the website
1. Start Ollama and launch the desktop overlay as described above.
2. Click **Open website** in the overlay. On the first visit, create a local account with a username and a password of at least 12 characters. Use the same account on future visits.
3. To ask about code from your editor, press **Ctrl+Alt+F8** while the editor has focus, then click **Open website**. The browser shows the attached snapshot's title. Repeat after editing to open a fresh snapshot. Use **Remove snapshot** to start a general conversation.

The website runs on this computer while the overlay is open, uses the same Ollama model, and needs no additional Python packages. The account database lives at `%APPDATA%\CodeLume\website-account.sqlite3` and stores a salted password hash. Chats and snapshots live in memory. The website uses a new local address when relaunched, so open it from the overlay each time.

To run the browser tutor without the overlay, run `.venv\Scripts\python website.py` from this folder and open the URL printed in the terminal. Keep that terminal open while using the website.
