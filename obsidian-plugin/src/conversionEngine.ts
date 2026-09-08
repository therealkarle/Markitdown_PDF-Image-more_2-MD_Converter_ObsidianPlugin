import { Plugin } from 'obsidian';
import { exec } from 'child_process';
import * as path from 'path';

export class ConversionEngine {
    private pythonBridge: PythonBridge;

    constructor(plugin: Plugin) {
        this.pythonBridge = new PythonBridge();
    }

    async convertFile(filePath: string, settings: any): Promise<string> {
        // First try Gemini Vision API
        try {
            const result = await this.pythonBridge.convertWithGemini(filePath, settings);
            return result;
        } catch (error) {
            console.error('Gemini conversion failed, falling back to local:', error);
            // Fall back to local markitdown
            return await this.pythonBridge.convertWithLocal(filePath, settings);
        }
    }

    async convertFolder(folderPath: string, settings: any): Promise<string[]> {
        const results: string[] = [];
        // Get all files in folder
        const files = this.getFilesInFolder(folderPath);
        for (const file of files) {
            try {
                const result = await this.convertFile(file, settings);
                results.push(result);
            } catch (error) {
                console.error(`Error converting ${file}:`, error);
            }
        }
        return results;
    }

    private getFilesInFolder(folderPath: string): string[] {
        // This would use Obsidian's vault API to get files
        return [];
    }
}

class PythonBridge {
    private pythonPath: string = 'python';

    async convertWithGemini(filePath: string, settings: any): Promise<string> {
        const scriptPath = path.join(__dirname, '..', 'scripts', 'convert_gemini.py');
        const cmd = `${this.pythonPath} "${scriptPath}" "${filePath}" "${settings.geminiApiKey}" "${settings.modelName}" "${settings.promptOverride}" "${settings.footerTemplate}"`;
        
        return new Promise((resolve, reject) => {
            exec(cmd, (error, stdout, stderr) => {
                if (error) {
                    reject(error);
                    return;
                }
                resolve(stdout);
            });
        });
    }

    async convertWithLocal(filePath: string, settings: any): Promise<string> {
        const scriptPath = path.join(__dirname, '..', 'scripts', 'convert_local.py');
        const cmd = `${this.pythonPath} "${scriptPath}" "${filePath}" "${settings.promptOverride}" "${settings.footerTemplate}"`;
        
        return new Promise((resolve, reject) => {
            exec(cmd, (error, stdout, stderr) => {
                if (error) {
                    reject(error);
                    return;
                }
                resolve(stdout);
            });
        });
    }
}