#include <filesystem>
#include <iostream>
#include <openvdb/openvdb.h>
#include <openvdb/io/File.h>
#include <oneapi/tbb/global_control.h>

namespace fs = std::filesystem;

template <typename Grid, typename Value>
typename Grid::Ptr grid(const std::string &name, const Value value,
                       const double size = 0.0625, const openvdb::Vec3d offset = {-1., -1., -1.}) {
    auto result = Grid::create(Value(0));
    result->setName(name);
    result->setGridClass(openvdb::GRID_FOG_VOLUME);
    auto transform = openvdb::math::Transform::createLinearTransform(size);
    transform->postTranslate(offset);
    result->setTransform(transform);
    result->fill(openvdb::CoordBBox({0, 0, 0}, {31, 31, 31}), value, true);
    // The current reader uses leaf bounds, so fixtures need actual leaves.
    result->tree().voxelizeActiveTiles();
    return result;
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    oneapi::tbb::global_control limit(oneapi::tbb::global_control::max_allowed_parallelism, 2);
    openvdb::initialize();
    const fs::path output(argv[1]);
    fs::create_directories(output);
    const auto save = [&](const std::string &name, openvdb::GridPtrVec grids) {
        const auto path = output / name;
        openvdb::io::File file(path.string());
        file.setCompression(openvdb::io::COMPRESS_ZIP);
        file.write(grids);
        file.close();
        std::cout << path << " " << fs::file_size(path) << "\n";
    };
    const auto defaults = [] {
        return openvdb::GridPtrVec{
            grid<openvdb::FloatGrid>("density", .2f),
            grid<openvdb::Vec3SGrid>("color", openvdb::Vec3s(1.f)),
            grid<openvdb::FloatGrid>("temperature", .1f)};
    };
    auto named = defaults();
    named.push_back(grid<openvdb::FloatGrid>("artist_density", 1.f));
    named.push_back(grid<openvdb::Vec3SGrid>("artist_color", openvdb::Vec3s(.2f, .5f, .8f)));
    named.push_back(grid<openvdb::FloatGrid>("artist_temperature", .4f));
    save("named-attributes.vdb", named);
    save("missing-standard-density.vdb", {
        grid<openvdb::FloatGrid>("artist_density", .7f),
        grid<openvdb::Vec3SGrid>("artist_color", openvdb::Vec3s(.2f, .5f, .8f))});
    auto transformed = defaults();
    transformed.push_back(grid<openvdb::FloatGrid>("artist_density", 1.f, .09, {.2, .1, 0.}));
    save("independent-grid-transforms.vdb", transformed);
    auto affine = grid<openvdb::FloatGrid>("artist_density", .8f);
    const openvdb::math::Mat4d matrix(
        .06, .025, 0., 0.,
        .015, .055, .008, 0.,
        .004, 0., .05, 0.,
        -1., -1., -.8, 1.);
    affine->setTransform(openvdb::math::Transform::createLinearTransform(matrix));
    auto accessor = affine->getAccessor();
    for (int z = 0; z < 32; ++z)
        for (int y = 0; y < 32; ++y)
            for (int x = 0; x < 32; ++x)
                accessor.setValue({x, y, z}, .2f + .02f * x);
    save("affine-grid.vdb", {affine});
    return 0;
}
