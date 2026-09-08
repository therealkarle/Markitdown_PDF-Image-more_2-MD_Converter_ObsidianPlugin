import { execFile } from 'child_process';

export interface ConversionOptions {
    // mode
    mode: string;
    // AI settings
    apiKey: string;
    modelName: string;
    promptOverride: string;
    aiMode: string;
    // OCR settings
    ocrPriority: string[];
    tesseractLang: string;
    azureOcrKey: string;
    azureOcrEndpoint: string;
}

export class ChildProcessBridge {
    async convertFile(filePath: string, options: ConversionOptions, scriptPath: string): Promise<string> {
        return new Promise((resolve, reject) => {
            execFile(
                'python',
                [scriptPath, filePath, JSON.stringify(options)],
                (error, stdout, stderr) => {
                    if (error) {
                        reject(`Error: ${error.message}`);
                        return;
                    }
                    if (stderr) {
                        console.warn(`Stderr: ${stderr}`);
                    }
                    resolve(stdout);
                },
            );
        });
    }
}
