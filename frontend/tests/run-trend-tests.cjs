const { spawnSync } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const output = mkdtempSync(path.join(tmpdir(), 'vibe-trend-test-'));

/**
 * 运行子进程并沿用当前终端输出，失败时返回对应退出码。
 *
 * @param {string} command 可执行文件路径
 * @param {string[]} args 命令参数
 * @param {NodeJS.ProcessEnv} [env] 可选环境变量
 * @returns {number} 子进程退出码
 */
function run(command, args, env = process.env) {
  const result = spawnSync(command, args, {
    cwd: root,
    env,
    stdio: 'inherit',
  });
  if (result.error) {
    console.error(result.error.message);
    return 1;
  }
  return result.status ?? 1;
}

try {
  const compiler = path.join(root, 'node_modules', 'typescript', 'bin', 'tsc');
  const source = path.join(root, 'src', 'features', 'workbench', 'trendEngine.ts');
  const compileCode = run(process.execPath, [
    compiler,
    source,
    '--target', 'ES2020',
    '--module', 'commonjs',
    '--moduleResolution', 'node',
    '--esModuleInterop',
    '--skipLibCheck',
    '--outDir', output,
  ]);
  if (compileCode !== 0) process.exitCode = compileCode;
  else {
    const testFile = path.join(root, 'tests', 'trendEngine.test.cjs');
    process.exitCode = run(process.execPath, ['--test', testFile], {
      ...process.env,
      TREND_ENGINE_JS: path.join(output, 'trendEngine.js'),
    });
  }
} finally {
  rmSync(output, { recursive: true, force: true });
}
