/*
 * Phase 2: /opt/bin に配置する実行ファイル。libevaldep.so にリンクする。
 *
 * Phase 3 の tesseract CLI（libtesseract.so にリンクする実行ファイル）と
 * 同じ構造。rpath を埋め込まずにビルドし、実行時に LD_LIBRARY_PATH 経由で
 * /opt/lib の依存が解決されるかを確認する。
 */

#include <stdio.h>
#include <stdlib.h>

extern int dep_multiply(int a, int b);
extern const char *dep_version(void);

int main(int argc, char **argv) {
  int a = 6;
  int b = 7;

  if (argc >= 3) {
    a = atoi(argv[1]);
    b = atoi(argv[2]);
  }

  printf("evaltool 1.0.0 (phase2)\n");
  printf("linked_lib=%s\n", dep_version());
  printf("dep_multiply(%d,%d)=%d\n", a, b, dep_multiply(a, b));

  return 0;
}
