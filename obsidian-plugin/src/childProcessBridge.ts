import { exec } from 'child_process';
import * as path from 'path';

export class ChildProcessBridge {
    async convertFile(filePath: string, apiKey: string, scriptPath: string): Promise<string> {
        return new Promise((resolve, reject) => {
            const command = `python "${scriptPath}" "${filePath}" "${apiKey}"`;
            exec(command, (error, stdout, stderr) => {
                if (error) {
                    reject(`Error: ${error.message}`);
                    return;
                }
                if (stderr) {
                    console.warn(`Stderr: ${stderr}`);
                }
                resolve(stdout);
            });
        });
    }
}
