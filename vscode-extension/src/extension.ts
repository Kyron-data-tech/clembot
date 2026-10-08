import * as vscode from 'vscode';
import * as http from 'http';

let isPolling = false;
let pollTimeout: NodeJS.Timeout | null = null;
const IPC_HOST = '127.0.0.1';
const IPC_PORT = 25362;

export function activate(context: vscode.ExtensionContext) {
    console.log('Clembot VS Code Extension is active.');

    const connectCmd = vscode.commands.registerCommand('clembot.connect', () => {
        startPolling();
        vscode.window.showInformationMessage('Clembot Voice Bridge connected.');
    });

    const disconnectCmd = vscode.commands.registerCommand('clembot.disconnect', () => {
        stopPolling();
        vscode.window.showInformationMessage('Clembot Voice Bridge disconnected.');
    });

    const statusCmd = vscode.commands.registerCommand('clembot.status', () => {
        const status = isPolling ? 'Connected and polling' : 'Disconnected';
        vscode.window.showInformationMessage(`Clembot Bridge Status: ${status}`);
    });

    context.subscriptions.push(connectCmd, disconnectCmd, statusCmd);

    // Auto-connect on startup
    startPolling();

    // Listen for active editor changes and push to Clembot
    vscode.window.onDidChangeActiveTextEditor(() => {
        pushEditorState();
    }, null, context.subscriptions);

    vscode.window.onDidChangeTextEditorSelection(() => {
        pushEditorState();
    }, null, context.subscriptions);
}

export function deactivate() {
    stopPolling();
}

function startPolling() {
    if (isPolling) return;
    isPolling = true;
    pushEditorState();
    pollLoop();
}

function stopPolling() {
    isPolling = false;
    if (pollTimeout) {
        clearTimeout(pollTimeout);
        pollTimeout = null;
    }
}

function pushEditorState() {
    const editor = vscode.window.activeTextEditor;
    const workspaceFolders = vscode.workspace.workspaceFolders;
    const workspaceRoot = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : null;

    let payload: any = {
        is_active: !!editor,
        workspace_folder: workspaceRoot,
        file_path: editor ? editor.document.uri.fsPath : null,
        file_name: editor ? editor.document.fileName.split(/[\\/]/).pop() : null,
        language_id: editor ? editor.document.languageId : null,
        cursor_line: editor ? editor.selection.active.line + 1 : 1,
        cursor_column: editor ? editor.selection.active.character + 1 : 1,
        selected_text: editor && !editor.selection.isEmpty ? editor.document.getText(editor.selection) : null,
        document_text: editor ? editor.document.getText() : null,
        total_lines: editor ? editor.document.lineCount : 0
    };

    makePostRequest('/vscode/state', payload, () => {});
}

function pollLoop() {
    if (!isPolling) return;

    makeGetRequest('/vscode/poll_command', (data) => {
        if (data && data.has_command && data.command) {
            handleCommand(data.command);
        }
        if (isPolling) {
            pollTimeout = setTimeout(pollLoop, 200);
        }
    }, () => {
        // Retry on error after delay
        if (isPolling) {
            pollTimeout = setTimeout(pollLoop, 2000);
        }
    });
}

async function handleCommand(cmd: any) {
    const id = cmd.id;
    const action = cmd.action;
    const params = cmd.params || {};

    let result: any = { id, success: false, action };

    try {
        const editor = vscode.window.activeTextEditor;

        switch (action) {
            case 'jump_to_line': {
                const lineNum = Math.max(1, params.line_number || 1) - 1;
                if (editor) {
                    const position = new vscode.Position(lineNum, 0);
                    editor.selection = new vscode.Selection(position, position);
                    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
                    result.success = true;
                    result.message = `Jumped to line ${lineNum + 1}`;
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'read_document': {
                if (editor) {
                    result.success = true;
                    result.file_path = editor.document.uri.fsPath;
                    result.content = editor.document.getText();
                    result.line_count = editor.document.lineCount;
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'open_file': {
                const filePath = params.file_path;
                if (filePath) {
                    const uri = vscode.Uri.file(filePath);
                    const doc = await vscode.workspace.openTextDocument(uri);
                    await vscode.window.showTextDocument(doc);
                    result.success = true;
                    result.message = `Opened ${filePath}`;
                }
                break;
            }

            case 'close_file':
            case 'close_active_file': {
                const filePath = params.file_path;
                let closed = false;
                if (filePath && vscode.window.tabGroups) {
                    const normTarget = filePath.toLowerCase().replace(/\\/g, '/');
                    const baseTarget = normTarget.split('/').pop() || normTarget;
                    for (const tabGroup of vscode.window.tabGroups.all) {
                        for (const tab of tabGroup.tabs) {
                            if (tab.input instanceof vscode.TabInputText) {
                                const tabPath = tab.input.uri.fsPath.toLowerCase().replace(/\\/g, '/');
                                if (tabPath === normTarget || tabPath.endsWith(normTarget) || tab.label.toLowerCase() === baseTarget) {
                                    await vscode.window.tabGroups.close(tab);
                                    closed = true;
                                    break;
                                }
                            }
                        }
                        if (closed) break;
                    }
                }
                if (!closed) {
                    await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
                }
                result.success = true;
                result.message = filePath ? `Closed ${filePath} in VS Code.` : 'Closed active file in VS Code.';
                break;
            }

            case 'apply_edit': {
                if (editor) {
                    const startLine = Math.max(1, params.start_line || 1) - 1;
                    // end_line is 1-indexed and inclusive; convert to 0-indexed and use end of that line
                    const endLineIdx = Math.max(startLine, (params.end_line || params.start_line || 1) - 1);
                    const endCol = params.end_col || editor.document.lineAt(Math.min(endLineIdx, editor.document.lineCount - 1)).range.end.character;
                    const newText = params.new_text || '';

                    const range = new vscode.Range(
                        new vscode.Position(startLine, params.start_col || 0),
                        new vscode.Position(endLineIdx, endCol)
                    );

                    const editSuccess = await editor.edit(editBuilder => {
                        editBuilder.replace(range, newText);
                    });

                    result.success = editSuccess;
                    result.message = editSuccess ? 'Edit applied successfully.' : 'Failed to apply edit in editor.';
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'save_document': {
                if (editor) {
                    await editor.document.save();
                    result.success = true;
                    result.message = 'Document saved.';
                }
                break;
            }

            case 'run_code': {
                if (editor) {
                    await editor.document.save();
                    const terminal = vscode.window.activeTerminal || vscode.window.createTerminal('Clembot Runner');
                    terminal.show();
                    const filePath = editor.document.uri.fsPath;
                    if (filePath.endsWith('.py')) {
                        terminal.sendText(`python "${filePath}"`);
                    } else {
                        terminal.sendText(`"${filePath}"`);
                    }
                    result.success = true;
                    result.message = 'Code execution started in terminal.';
                }
                break;
            }

            case 'undo': {
                await vscode.commands.executeCommand('undo');
                result.success = true;
                result.message = 'Undo applied.';
                break;
            }

            case 'inspect_context': {
                if (editor) {
                    const line = editor.selection.active.line;
                    const selectedText = editor.document.getText(editor.selection);
                    const totalLines = editor.document.lineCount;
                    const startLine = Math.max(0, line - 15);
                    const endLine = Math.min(totalLines - 1, line + 15);
                    const snippetRange = new vscode.Range(
                        new vscode.Position(startLine, 0),
                        new vscode.Position(endLine, editor.document.lineAt(endLine).range.end.character)
                    );
                    result.success = true;
                    result.file_path = editor.document.uri.fsPath;
                    result.line = line + 1;
                    result.selected_text = selectedText;
                    result.code_snippet = editor.document.getText(snippetRange);
                    result.total_lines = totalLines;
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'go_to_definition': {
                await vscode.commands.executeCommand('editor.action.revealDefinition');
                result.success = true;
                result.message = 'Going to definition.';
                break;
            }

            case 'rename_symbol': {
                const newName = params.new_name;
                if (newName) {
                    // Position cursor first if line provided
                    if (params.line_number && editor) {
                        const pos = new vscode.Position(Math.max(0, params.line_number - 1), params.column || 0);
                        editor.selection = new vscode.Selection(pos, pos);
                    }
                    await vscode.commands.executeCommand('editor.action.rename', [newName]);
                    result.success = true;
                    result.message = `Renamed to ${newName}.`;
                } else {
                    result.error = 'new_name param required for rename_symbol';
                }
                break;
            }

            case 'format_document': {
                await vscode.commands.executeCommand('editor.action.formatDocument');
                result.success = true;
                result.message = 'Document formatted.';
                break;
            }

            case 'format_selection': {
                await vscode.commands.executeCommand('editor.action.formatSelection');
                result.success = true;
                result.message = 'Selection formatted.';
                break;
            }

            case 'select_line': {
                if (editor) {
                    const lineNum = Math.max(1, params.line_number || (editor.selection.active.line + 1)) - 1;
                    const line = editor.document.lineAt(Math.min(lineNum, editor.document.lineCount - 1));
                    const selection = new vscode.Selection(line.range.start, line.range.end);
                    editor.selection = selection;
                    editor.revealRange(line.range, vscode.TextEditorRevealType.InCenter);
                    result.success = true;
                    result.message = `Line ${lineNum + 1} selected.`;
                    result.selected_text = editor.document.getText(line.range);
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'toggle_comment': {
                if (editor && params.line_number) {
                    const lineNum = Math.max(1, params.line_number) - 1;
                    const endNum = params.end_line ? Math.max(1, params.end_line) - 1 : lineNum;
                    const start = new vscode.Position(lineNum, 0);
                    const end = new vscode.Position(endNum, editor.document.lineAt(Math.min(endNum, editor.document.lineCount - 1)).range.end.character);
                    editor.selection = new vscode.Selection(start, end);
                }
                await vscode.commands.executeCommand('editor.action.commentLine');
                result.success = true;
                result.message = 'Comment toggled.';
                break;
            }

            case 'duplicate_line': {
                if (editor) {
                    if (params.line_number) {
                        const lineNum = Math.max(1, params.line_number) - 1;
                        const pos = new vscode.Position(lineNum, 0);
                        editor.selection = new vscode.Selection(pos, pos);
                    }
                    await vscode.commands.executeCommand('editor.action.copyLinesDownAction');
                    result.success = true;
                    result.message = 'Line duplicated.';
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'move_line_up': {
                const moveUpCount = params.count || 1;
                for (let i = 0; i < moveUpCount; i++) {
                    await vscode.commands.executeCommand('editor.action.moveLinesUpAction');
                }
                result.success = true;
                result.message = `Moved line up ${moveUpCount} time(s).`;
                break;
            }

            case 'move_line_down': {
                const moveDownCount = params.count || 1;
                for (let i = 0; i < moveDownCount; i++) {
                    await vscode.commands.executeCommand('editor.action.moveLinesDownAction');
                }
                result.success = true;
                result.message = `Moved line down ${moveDownCount} time(s).`;
                break;
            }

            case 'redo': {
                await vscode.commands.executeCommand('redo');
                result.success = true;
                result.message = 'Redo applied.';
                break;
            }

            case 'get_line_text': {
                if (editor) {
                    const lineNum = Math.max(1, params.line_number || (editor.selection.active.line + 1)) - 1;
                    const lineIdx = Math.min(lineNum, editor.document.lineCount - 1);
                    const lineText = editor.document.lineAt(lineIdx).text;
                    result.success = true;
                    result.line = lineIdx + 1;
                    result.text = lineText;
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'get_selection_range': {
                if (editor) {
                    const sel = editor.selection;
                    result.success = true;
                    result.start_line = sel.start.line + 1;
                    result.start_col = sel.start.character + 1;
                    result.end_line = sel.end.line + 1;
                    result.end_col = sel.end.character + 1;
                    result.selected_text = editor.document.getText(sel);
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'insert_snippet': {
                if (editor && params.snippet) {
                    if (params.line_number) {
                        const lineNum = Math.max(1, params.line_number) - 1;
                        const col = params.column || 0;
                        const pos = new vscode.Position(lineNum, col);
                        editor.selection = new vscode.Selection(pos, pos);
                    }
                    await editor.insertSnippet(new vscode.SnippetString(params.snippet));
                    result.success = true;
                    result.message = 'Snippet inserted.';
                } else {
                    result.error = !editor ? 'No active editor' : 'snippet param required';
                }
                break;
            }

            case 'delete_lines': {
                if (editor) {
                    const startLine = Math.max(1, params.start_line || params.line_number || 1) - 1;
                    const endLine = params.end_line ? Math.max(1, params.end_line) - 1 : startLine;
                    const lineCount = editor.document.lineCount;
                    const clampedEnd = Math.min(endLine, lineCount - 1);

                    const editSuccess = await editor.edit(editBuilder => {
                        // Include newline so the lines are fully removed
                        const startPos = new vscode.Position(startLine, 0);
                        const afterEnd = clampedEnd + 1 < lineCount
                            ? new vscode.Position(clampedEnd + 1, 0)
                            : new vscode.Position(clampedEnd, editor!.document.lineAt(clampedEnd).range.end.character);
                        editBuilder.delete(new vscode.Range(startPos, afterEnd));
                    });

                    result.success = editSuccess;
                    result.message = editSuccess
                        ? `Deleted lines ${startLine + 1}–${clampedEnd + 1}.`
                        : 'Failed to delete lines.';
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'insert_line': {
                if (editor) {
                    const lineNum = Math.max(1, params.line_number || 1) - 1;
                    const text = params.text || '';
                    const lineCount = editor.document.lineCount;
                    const insertPos = lineNum < lineCount
                        ? new vscode.Position(lineNum, 0)
                        : new vscode.Position(lineCount - 1, editor.document.lineAt(lineCount - 1).range.end.character);

                    const editSuccess = await editor.edit(editBuilder => {
                        if (lineNum < lineCount) {
                            editBuilder.insert(insertPos, text + '\n');
                        } else {
                            editBuilder.insert(insertPos, '\n' + text);
                        }
                    });

                    result.success = editSuccess;
                    result.message = editSuccess ? `Inserted line at ${lineNum + 1}.` : 'Failed to insert line.';
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'replace_line': {
                if (editor) {
                    const lineNum = Math.max(1, params.line_number || 1) - 1;
                    const lineIdx = Math.min(lineNum, editor.document.lineCount - 1);
                    const newText = params.new_text ?? params.text ?? '';
                    const line = editor.document.lineAt(lineIdx);

                    const editSuccess = await editor.edit(editBuilder => {
                        editBuilder.replace(line.range, newText);
                    });

                    result.success = editSuccess;
                    result.message = editSuccess ? `Line ${lineIdx + 1} replaced.` : 'Failed to replace line.';
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            case 'find_and_replace': {
                if (editor) {
                    const search = params.search || '';
                    const replacement = params.replace ?? '';
                    const allText = editor.document.getText();
                    const useRegex = params.use_regex === true;

                    let newText: string;
                    if (useRegex) {
                        newText = allText.replace(new RegExp(search, 'g'), replacement);
                    } else {
                        newText = allText.split(search).join(replacement);
                    }

                    const fullRange = new vscode.Range(
                        new vscode.Position(0, 0),
                        new vscode.Position(editor.document.lineCount - 1, editor.document.lineAt(editor.document.lineCount - 1).range.end.character)
                    );

                    const editSuccess = await editor.edit(editBuilder => {
                        editBuilder.replace(fullRange, newText);
                    });

                    result.success = editSuccess;
                    result.message = editSuccess ? `Replaced all occurrences of "${search}".` : 'Find-and-replace failed.';
                } else {
                    result.error = 'No active editor';
                }
                break;
            }

            default:
                result.error = `Unknown action: ${action}`;
        }
    } catch (e: any) {
        result.error = e.message || String(e);
    }

    makePostRequest('/vscode/command_result', result, () => {});
    pushEditorState();
}

function makeGetRequest(path: string, onSuccess: (data: any) => void, onError: (err: any) => void) {
    const options = {
        hostname: IPC_HOST,
        port: IPC_PORT,
        path: path,
        method: 'GET',
        timeout: 3000
    };

    const req = http.request(options, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
            try {
                const parsed = JSON.parse(body);
                onSuccess(parsed);
            } catch (e) {
                onError(e);
            }
        });
    });

    req.on('error', (e) => onError(e));
    req.on('timeout', () => { req.destroy(); onError(new Error('Timeout')); });
    req.end();
}

function makePostRequest(path: string, data: any, onSuccess: (data: any) => void) {
    const postData = JSON.stringify(data);
    const options = {
        hostname: IPC_HOST,
        port: IPC_PORT,
        path: path,
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(postData)
        },
        timeout: 3000
    };

    const req = http.request(options, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
            try {
                const parsed = JSON.parse(body);
                onSuccess(parsed);
            } catch (e) {
                onSuccess({});
            }
        });
    });

    req.on('error', () => {});
    req.write(postData);
    req.end();
}
