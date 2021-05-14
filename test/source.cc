#include "some_pch.h"
#include <string>
#include <algorithm>
#include <memory>
#include <vector>
#include <unordered_map>
#include <chrono>
#include <iostream>
#include <fstream>
#include <cmath>

#define CODEAI_EXPORT
#define CODEAI_EXPORT_INIT

class TestClass {
public:
    TestClass(float a): a_(a){}
    static std::unique_ptr<TestClass> CODEAI_EXPORT_INIT create(float a){
        return std::make_unique<TestClass>(a);
    }
    float CODEAI_EXPORT add(float b){
        return a_ + b;
    }
    float CODEAI_EXPORT mul(float b){
        return a_ * b;
    }
private:
    float a_;
};

float CODEAI_EXPORT sub(float a, float b){
    return a - b;
}
