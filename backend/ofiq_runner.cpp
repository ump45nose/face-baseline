#include <memory>
#include <cstring>
#include <map>
#include <cstdint>
#include <iostream>
#include <iomanip>
#include <cmath>
#include "ofiq_lib.h"

// One engine instance per serial worker. stdin carries width/height/RGB pixels;
// stdout is JSON lines; upstream diagnostics go to stderr.
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    auto output = std::cout.rdbuf();
    std::cout.rdbuf(std::cerr.rdbuf());
    auto engine = OFIQ::Interface::getImplementation();
    auto init = engine->initialize(argv[1], "ofiq_config.jaxn");
    int major, minor, patch;
    engine->getVersion(major, minor, patch);
    std::ostream result(output);
    result << "{\"version\":\"" << major << '.' << minor << '.' << patch
           << "\",\"code\":" << static_cast<int>(init.code) << "}" << std::endl;
    if (init.code != OFIQ::ReturnCode::Success) return 1;
    uint32_t width, height;
    while (std::cin.read(reinterpret_cast<char*>(&width), 4)) {
        if (!std::cin.read(reinterpret_cast<char*>(&height), 4)) return 2;
        size_t size = static_cast<size_t>(width) * height * 3;
        auto pixels = std::shared_ptr<uint8_t[]>(new uint8_t[size]);
        if (!std::cin.read(reinterpret_cast<char*>(pixels.get()), size)) return 2;
        OFIQ::Image image(static_cast<uint16_t>(width), static_cast<uint16_t>(height), 24, pixels);
        OFIQ::FaceImageQualityAssessment qa;
        OFIQ::FaceImageQualityPreprocessingResult pre;
        auto status = engine->vectorQualityWithPreprocessingResults(image, qa, pre,
                            static_cast<uint32_t>(OFIQ::PreprocessingResultType::Faces));
        result << "{\"code\":" << static_cast<int>(status.code)
               << ",\"faces\":" << pre.m_faces.size() << ",\"metrics\":{";
        bool first = true;
        for (auto const& [measure, value] : qa.qAssessments) {
            if (!first) result << ',';
            first = false;
            result << '"' << static_cast<int>(measure) << "\":{\"raw\":";
            if (std::isfinite(value.rawScore)) result << std::setprecision(15) << value.rawScore;
            else result << "null";
            result << ",\"scalar\":";
            if (std::isfinite(value.scalar)) result << value.scalar;
            else result << "null";
            result << ",\"code\":" << static_cast<int>(value.code) << '}';
        }
        result << "}}" << std::endl;
    }
}
