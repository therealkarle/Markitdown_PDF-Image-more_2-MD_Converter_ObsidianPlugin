import { Plugin, PluginSettingTab, Setting, Notice, App } from 'obsidian';
import * as fs from 'fs';
import * as path from 'path';
import { ChildProcessBridge, ConversionOptions } from './childProcessBridge';
import { DEFAULT_SETTINGS, OcrEngine, PluginSettings } from './settings';

export default class MarkItDownPlugin extends Plugin {
    declare settings: PluginSettings;
    bridge!: ChildProcessBridge;

    async onload() {
        await this.loadSettings();
        this.bridge = new ChildProcessBridge();
        this.addSettingTab(new MarkItDownSettingTab(this.app, this));
        this.addRibbonIcon('document-operations', 'MarkItDown Pro', () => {
            new Notice('MarkItDown Pro is ready!');
        });
        this.addCommand({
            id: 'convert-active-file',
            name: 'Convert Active File to Markdown',
            callback: () => this.convertActiveFile(),
        });
    }

    onunload() {
        console.log('Unloading MarkItDown Pro');
    }

    async loadSettings() {
        const data = await this.loadData();
        this.settings = { ...DEFAULT_SETTINGS, ...data };
    }

    async saveSettings() {
        await this.saveData(this.settings);
        await this.updateEnvFile();
    }

    async updateEnvFile() {
        try {
            const pluginDir = (this.app.vault.adapter as any).getBasePath()
                + path.sep + '.obsidian' + path.sep + 'plugins' + path.sep + 'markitdown-pro';
            const envPath = path.join(pluginDir, '.env');
            const content = [
                `GEMINI_API_KEY=${this.settings.geminiApiKey}`,
                `AZURE_OCR_KEY=${this.settings.azureOcrKey}`,
                `AZURE_OCR_ENDPOINT=${this.settings.azureOcrEndpoint}`,
            ].join('\n') + '\n';
            fs.mkdirSync(pluginDir, { recursive: true });
            fs.writeFileSync(envPath, content, 'utf8');
        } catch (error) {
            console.error('Failed to update .env file:', error);
            new Notice('Failed to update .env file. Check console for details.');
        }
    }

    async convertActiveFile() {
        const activeFile = this.app.workspace.getActiveFile();
        if (!activeFile) { new Notice('No active file to convert.'); return; }

        try {
            new Notice('Converting file…');
            const scriptPath = path.join(__dirname, '..', 'scripts', 'convert.py');

            const options: ConversionOptions = {
                useMarkitdown:   this.settings.useMarkitdown,
                useOcr:          this.settings.useOcr,
                useAi:           this.settings.useAi,
                blockPriority:   this.settings.blockPriority,
                ocrPriority:     this.settings.ocrPriority,
                aiAutoDetect:    this.settings.aiAutoDetect,
                aiImprove:       this.settings.aiImprove,
                geminiApiKey:    this.settings.geminiApiKey,
                azureOcrKey:     this.settings.azureOcrKey,
                azureOcrEndpoint: this.settings.azureOcrEndpoint,
                tesseractLang:   this.settings.tesseractLang,
                tesseractCmd:    this.settings.tesseractCmd,
                modelName:       this.settings.modelName,
                promptOverride:  this.settings.promptOverride,
            };

            const result = await this.bridge.convertFile(activeFile.path, options, scriptPath);
            const footer = this.settings.footerTemplate
                .replace('{{date}}', new Date().toISOString().split('T')[0])
                .replace('{{model}}', this.settings.modelName);
            const outputPath = activeFile.path.replace(/\.[^.]+$/, '') + '.md';
            await this.app.vault.create(outputPath, result + footer);
            new Notice('Conversion complete: ' + outputPath);
        } catch (error) {
            console.error('Conversion error:', error);
            const message = error instanceof Error ? error.message : String(error);
            new Notice(`Conversion failed: ${message}`);
        }
    }
}

class MarkItDownSettingTab extends PluginSettingTab {
    plugin: MarkItDownPlugin;
    private ocrSection!: HTMLElement;
    private aiSection!: HTMLElement;

    constructor(app: App, plugin: MarkItDownPlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const { containerEl } = this;
        containerEl.empty();
        containerEl.createEl('h2', { text: 'MarkItDown Pro Settings' });

        // ── 1. Method toggles ─────────────────────────────────────────────────
        containerEl.createEl('h3', { text: 'Methods' });

        new Setting(containerEl)
            .setName('Use MarkItDown')
            .setDesc('Native conversion for PDF, Word, HTML, and more.')
            .addToggle(t => t.setValue(this.plugin.settings.useMarkitdown)
                .onChange(async v => {
                    this.plugin.settings.useMarkitdown = v;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Use OCR')
            .setDesc('Tesseract / Azure Computer Vision / Windows OCR.')
            .addToggle(t => t.setValue(this.plugin.settings.useOcr)
                .onChange(async v => {
                    this.plugin.settings.useOcr = v;
                    await this.plugin.saveSettings();
                    this.updateVisibility();
                }));

        new Setting(containerEl)
            .setName('Use AI  (Gemini)')
            .setDesc('Gemini as a generator, or enable Auto-Detect / Improve below.')
            .addToggle(t => t.setValue(this.plugin.settings.useAi)
                .onChange(async v => {
                    this.plugin.settings.useAi = v;
                    await this.plugin.saveSettings();
                    this.updateVisibility();
                }));

        new Setting(containerEl)
            .setName('Priority order')
            .setDesc('Comma-separated block order: markitdown, ocr, ai')
            .addText(t => t
                .setPlaceholder('markitdown,ocr,ai')
                .setValue(this.plugin.settings.blockPriority.join(','))
                .onChange(async v => {
                    this.plugin.settings.blockPriority = v.split(',').map(s => s.trim()).filter(Boolean);
                    await this.plugin.saveSettings();
                }));

        // ── 2. OCR section ────────────────────────────────────────────────────
        this.ocrSection = containerEl.createEl('div');
        this.ocrSection.createEl('h3', { text: 'OCR Settings' });

        new Setting(this.ocrSection)
            .setName('OCR sub-engine priority')
            .setDesc('Comma-separated: tesseract, azure_ocr, win_ocr')
            .addText(t => t
                .setPlaceholder('tesseract,azure_ocr')
                .setValue(this.plugin.settings.ocrPriority.join(','))
                .onChange(async v => {
                    this.plugin.settings.ocrPriority = v.split(',').map(s => s.trim()).filter(Boolean) as OcrEngine[];
                    await this.plugin.saveSettings();
                }));

        new Setting(this.ocrSection)
            .setName('Tesseract language')
            .addText(t => t.setPlaceholder('deu+eng')
                .setValue(this.plugin.settings.tesseractLang)
                .onChange(async v => { this.plugin.settings.tesseractLang = v; await this.plugin.saveSettings(); }));

        new Setting(this.ocrSection)
            .setName('Tesseract executable')
            .setDesc('Optional full path to tesseract.exe. Leave empty for automatic detection.')
            .addText(t => t.setPlaceholder('C:\\Program Files\\Tesseract-OCR\\tesseract.exe')
                .setValue(this.plugin.settings.tesseractCmd)
                .onChange(async v => { this.plugin.settings.tesseractCmd = v; await this.plugin.saveSettings(); }));

        new Setting(this.ocrSection)
            .setName('Azure OCR Endpoint')
            .addText(t => t.setPlaceholder('https://<resource>.cognitiveservices.azure.com')
                .setValue(this.plugin.settings.azureOcrEndpoint)
                .onChange(async v => { this.plugin.settings.azureOcrEndpoint = v; await this.plugin.saveSettings(); }));

        new Setting(this.ocrSection)
            .setName('Azure OCR Key')
            .addText(t => {
                t.inputEl.type = 'password';
                t.setPlaceholder('Azure key…').setValue(this.plugin.settings.azureOcrKey)
                    .onChange(async v => { this.plugin.settings.azureOcrKey = v; await this.plugin.saveSettings(); });
            });

        // ── 3. AI section ─────────────────────────────────────────────────────
        this.aiSection = containerEl.createEl('div');
        this.aiSection.createEl('h3', { text: 'AI Settings  (Gemini)' });

        new Setting(this.aiSection)
            .setName('Auto-Detect')
            .setDesc('Gemini inspects the file and picks the best method.')
            .addToggle(t => t.setValue(this.plugin.settings.aiAutoDetect)
                .onChange(async v => { this.plugin.settings.aiAutoDetect = v; await this.plugin.saveSettings(); }));

        new Setting(this.aiSection)
            .setName('Improve')
            .setDesc('Gemini post-processes every result to clean up and improve quality.')
            .addToggle(t => t.setValue(this.plugin.settings.aiImprove)
                .onChange(async v => { this.plugin.settings.aiImprove = v; await this.plugin.saveSettings(); }));

        new Setting(this.aiSection)
            .setName('Gemini API Key')
            .addText(t => {
                t.inputEl.type = 'password';
                t.setPlaceholder('Gemini key…').setValue(this.plugin.settings.geminiApiKey)
                    .onChange(async v => { this.plugin.settings.geminiApiKey = v; await this.plugin.saveSettings(); });
            });

        new Setting(this.aiSection)
            .setName('Gemini Model')
            .addDropdown(d => d
                .addOption('gemini-2.0-flash-lite-preview-02-05', 'Gemini 2.0 Flash-Lite')
                .addOption('gemini-1.5-flash', 'Gemini 1.5 Flash')
                .addOption('gemini-1.5-pro', 'Gemini 1.5 Pro')
                .setValue(this.plugin.settings.modelName)
                .onChange(async v => { this.plugin.settings.modelName = v; await this.plugin.saveSettings(); }));

        new Setting(this.aiSection)
            .setName('Prompt override')
            .setDesc('Custom system instruction. Leave empty for the built-in prompt.')
            .addTextArea(t => t.setPlaceholder('Optional…')
                .setValue(this.plugin.settings.promptOverride)
                .onChange(async v => { this.plugin.settings.promptOverride = v; await this.plugin.saveSettings(); }));

        // ── 4. Misc ───────────────────────────────────────────────────────────
        containerEl.createEl('h3', { text: 'Misc' });

        new Setting(containerEl)
            .setName('Footer template')
            .setDesc('Use {{date}} and {{model}} as placeholders.')
            .addText(t => t.setValue(this.plugin.settings.footerTemplate)
                .onChange(async v => { this.plugin.settings.footerTemplate = v; await this.plugin.saveSettings(); }));

        new Setting(containerEl)
            .setName('Use separate plugin settings')
            .addToggle(t => t.setValue(this.plugin.settings.useSeparatePluginSettings)
                .onChange(async v => { this.plugin.settings.useSeparatePluginSettings = v; await this.plugin.saveSettings(); }));

        this.updateVisibility();
    }

    private updateVisibility(): void {
        this.ocrSection.style.display = this.plugin.settings.useOcr ? '' : 'none';
        this.aiSection.style.display  = this.plugin.settings.useAi  ? '' : 'none';
    }
}
