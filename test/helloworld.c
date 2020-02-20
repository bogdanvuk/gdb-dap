#include <stdio.h>

int test(int b) {
    return b + 2;
}

int main() {
    int a = 0;
    printf("Hello, World!");
    a = test(a);
    return 0;
}
