import { Plugin, PluginSettingTab, Setting, Notice, App, TFile } from 'obsidian';
import * as fs from 'fs';
import * as path from 'path';
import { ChildProcessBridge, ConversionOptions } from './childProcessBridge';
import { DEFAULT_SETTINGS, ConversionMode, AiMode, MarkdownGenerator, PluginSettings } from './settings';

const SHARED_SETTINGS_FILE = 'markitdown-settings.json';

export default class MarkItDownPlugin extends Plugin {
    declare settings: PluginSettings;
    bridge!: ChildProcessBridge;

    async onload() {
        await this.loadSettings();
        this.bridge = new ChildProcessBridge();
        this.addSettingTab(new MarkItDownSettingTab(this.app, this));
        this.addRibbonIcon('document-operations', 'MarkItDown Pro', (evt: MouseEvent) => {
            new Notice('MarkItDown Pro is ready!');
        });
        this.addCommand({
            id: 'convert-active-file',
            name: 'Convert Active File to Markdown',
            callback: () => this.convertActiveFile()
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
            const pluginDir = (this.app.vault.adapter as any).getBasePath() + path.sep + '.obsidian' + path.sep + 'plugins' + path.sep + 'markitdown-pro';
            const envPath = path.join(pluginDir, '.env');
            const envContent = [
                `GEMINI_API_KEY=${this.settings.geminiApiKey}`,
                `AZURE_OCR_KEY=${this.settings.azureOcrKey}`,
            ].join('\n') + '\n';
            fs.mkdirSync(pluginDir, { recursive: true });
            fs.writeFileSync(envPath, envContent, 'utf8');
        } catch (error) {
            console.error('Failed to update .env file:', error);
            new Notice('Failed to update .env file. Check console for details.');
        }
    }

    async convertActiveFile() {
        const activeFile = this.app.workspace.getActiveFile();
        if (!activeFile) {
            new Notice('No active file to convert.');
            return;
        }

        try {
            new Notice('Converting file...');
            const scriptPath = path.join(__dirname, '..', 'scripts', 'convert.py');

            const conversionOptions: ConversionOptions = {
                mode: this.settings.mode,
                apiKey: this.settings.geminiApiKey,
                modelName: this.settings.modelName,
                promptOverride: this.settings.promptOverride,
                aiMode: this.settings.aiMode,
                ocrPriority: this.settings.ocrPriority,
                tesseractLang: this.settings.tesseractLang,
                azureOcrKey: this.settings.azureOcrKey,
                azureOcrEndpoint: this.settings.azureOcrEndpoint,
            };

            const result = await this.bridge.convertFile(
                activeFile.path,
                conversionOptions,
                scriptPath
            );

            const footer = this.settings.footerTemplate
                .replace('{{date}}', new Date().toISOString().split('T')[0])
                .replace('{{model}}', this.settings.modelName);

            const output = result + footer;
            const outputPath = activeFile.path.replace(/\.[^.]+$/, '') + '.md';

            await this.app.vault.create(outputPath, output);
            new Notice('Conversion complete: ' + outputPath);
        } catch (error) {
            console.error('Conversion error:', error);
            new Notice('Conversion failed. Check console for details.');
        }
    }
}

class MarkItDownSettingTab extends PluginSettingTab {
    plugin: MarkItDownPlugin;
    // section containers for conditional visibility
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

        // ── 1. Conversion Mode ──────────────────────────────────────────────
        containerEl.createEl('h3', { text: 'Conversion Mode' });

        new Setting(containerEl)
            .setName('Mode')
            .setDesc('Simple: MarkItDown native (PDF, Word…) | OCR: Tesseract / Azure / Windows OCR chain | AI Enhanced: OCR + Gemini improvement')
            .addDropdown(dropdown => dropdown
                .addOption('simple', 'Simple (MarkItDown native)')
                .addOption('ocr', 'OCR')
                .addOption('ai_enhanced', 'AI Enhanced')
                .setValue(this.plugin.settings.mode)
                .onChange(async (value) => {
                    this.plugin.settings.mode = value as ConversionMode;
                    await this.plugin.saveSettings();
                    this.updateSectionVisibility(value as ConversionMode);
                }));

        // ── 2. OCR Settings ─────────────────────────────────────────────────
        this.ocrSection = containerEl.createEl('div');
        this.ocrSection.createEl('h3', { text: 'OCR Settings' });

        new Setting(this.ocrSection)
            .setName('OCR Priority Chain')
            .setDesc('Comma-separated list of OCR engines in fallback order. Options: tesseract, azure_ocr, win_ocr')
            .addText(text => text
                .setPlaceholder('tesseract,azure_ocr')
                .setValue(this.plugin.settings.ocrPriority.join(','))
                .onChange(async (value) => {
                    this.plugin.settings.ocrPriority = value
                        .split(',')
                        .map(s => s.trim())
                        .filter(Boolean) as MarkdownGenerator[];
                    await this.plugin.saveSettings();
                }));

        new Setting(this.ocrSection)
            .setName('Tesseract Language')
            .setDesc('Language code(s) for Tesseract OCR, e.g. deu+eng')
            .addText(text => text
                .setPlaceholder('deu+eng')
                .setValue(this.plugin.settings.tesseractLang)
                .onChange(async (value) => {
                    this.plugin.settings.tesseractLang = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(this.ocrSection)
            .setName('Azure OCR Endpoint')
            .setDesc('Azure Computer Vision endpoint URL')
            .addText(text => text
                .setPlaceholder('https://<resource>.cognitiveservices.azure.com')
                .setValue(this.plugin.settings.azureOcrEndpoint)
                .onChange(async (value) => {
                    this.plugin.settings.azureOcrEndpoint = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(this.ocrSection)
            .setName('Azure OCR Key')
            .setDesc('Azure Computer Vision API key. Saved to .env file.')
            .addText(text => {
                text.inputEl.type = 'password';
                text.setPlaceholder('Enter Azure OCR key...')
                    .setValue(this.plugin.settings.azureOcrKey)
                    .onChange(async (value) => {
                        this.plugin.settings.azureOcrKey = value;
                        await this.plugin.saveSettings();
                    });
            });

        // ── 3. AI Settings ──────────────────────────────────────────────────
        this.aiSection = containerEl.createEl('div');
        this.aiSection.createEl('h3', { text: 'AI Settings (Gemini)' });

        new Setting(this.aiSection)
            .setName('AI Role')
            .setDesc('Fallback: Gemini runs only when all other engines fail. Enhancement: Gemini always improves the primary result.')
            .addDropdown(dropdown => dropdown
                .addOption('fallback', 'Fallback (AI only when others fail)')
                .addOption('enhancement', 'Enhancement (AI improves every result)')
                .setValue(this.plugin.settings.aiMode)
                .onChange(async (value) => {
                    this.plugin.settings.aiMode = value as AiMode;
                    await this.plugin.saveSettings();
                }));

        new Setting(this.aiSection)
            .setName('Gemini API Key')
            .setDesc('Your Google Gemini API key. Saved to the plugin .env file.')
            .addText(text => {
                text.inputEl.type = 'password';
                text.setPlaceholder('Enter your Gemini key...')
                    .setValue(this.plugin.settings.geminiApiKey)
                    .onChange(async (value) => {
                        this.plugin.settings.geminiApiKey = value;
                        await this.plugin.saveSettings();
                    });
            });

        new Setting(this.aiSection)
            .setName('Gemini Model')
            .setDesc('Select the Gemini model to use.')
            .addDropdown(dropdown => dropdown
                .addOption('gemini-2.0-flash-lite-preview-02-05', 'Gemini 2.0 Flash-Lite')
                .addOption('gemini-1.5-flash', 'Gemini 1.5 Flash')
                .addOption('gemini-1.5-pro', 'Gemini 1.5 Pro')
                .setValue(this.plugin.settings.modelName)
                .onChange(async (value) => {
                    this.plugin.settings.modelName = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(this.aiSection)
            .setName('Prompt Override')
            .setDesc('Custom system instructions for Gemini. Leave empty for the built-in enhancement prompt.')
            .addTextArea(text => text
                .setPlaceholder('Optional custom instructions...')
                .setValue(this.plugin.settings.promptOverride)
                .onChange(async (value) => {
                    this.plugin.settings.promptOverride = value;
                    await this.plugin.saveSettings();
                }));

        // ── 4. Misc ─────────────────────────────────────────────────────────
        containerEl.createEl('h3', { text: 'Misc' });

        new Setting(containerEl)
            .setName('Footer Template')
            .setDesc('Appended to every converted file. Use {{date}} and {{model}} as placeholders.')
            .addText(text => text
                .setPlaceholder('\\n\\n---\\nConverted on {{date}}')
                .setValue(this.plugin.settings.footerTemplate)
                .onChange(async (value) => {
                    this.plugin.settings.footerTemplate = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Use Separate Plugin Settings')
            .setDesc('When enabled, settings are stored separately from the shared markitdown-settings.json.')
            .addToggle(toggle => toggle
                .setValue(this.plugin.settings.useSeparatePluginSettings)
                .onChange(async (value) => {
                    this.plugin.settings.useSeparatePluginSettings = value;
                    await this.plugin.saveSettings();
                }));

        // Apply initial visibility
        this.updateSectionVisibility(this.plugin.settings.mode);
    }

    private updateSectionVisibility(mode: ConversionMode): void {
        const showOcr = mode === 'ocr' || mode === 'ai_enhanced';
        const showAi = mode === 'ai_enhanced';
        this.ocrSection.style.display = showOcr ? '' : 'none';
        this.aiSection.style.display = showAi ? '' : 'none';
    }
}