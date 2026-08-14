/*
 * Phase 2: 「依存される側」の共有ライブラリ。
 *
 * libevalmain.so と実行ファイル evaltool の双方から参照される。
 * Phase 3 における libleptonica.so（libtesseract.so と tesseract の
 * 双方から参照される）に相当する位置づけ。
 */

#define LIBEVALDEP_VERSION "libevaldep 1.0.0 (phase2)"

int dep_multiply(int a, int b) { return a * b; }

const char *dep_version(void) { return LIBEVALDEP_VERSION; }
