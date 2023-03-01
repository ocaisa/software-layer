# Hooks to customize how EasyBuild installs software in EESSI
# see https://docs.easybuild.io/en/latest/Hooks.html
import os
import re

from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.config import build_option, update_build_option
from easybuild.tools.systemtools import AARCH64, POWER, X86_64, get_cpu_architecture, get_cpu_features
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC

EESSI_RPATH_OVERRIDE_ATTR = "orig_rpath_override_dirs"

CUDA_ENABLED_TOOLCHAINS = [
    "fosscuda",
    "gcccuda",
    "gimpic",
    "giolfc",
    "gmklc",
    "golfc",
    "gomklc",
    "gompic",
    "goolfc",
    "iccifortcuda",
    "iimklc",
    "iimpic",
    "intelcuda",
    "iomklc",
    "iompic",
    "nvompic",
    "nvpsmpic",
]


def parse_hook(ec, *args, **kwargs):
    """Main parse hook: trigger custom functions based on software name."""

    # determine path to Prefix installation in compat layer via $EPREFIX
    eprefix = get_eessi_envvar("EPREFIX")

    if ec.name in PARSE_HOOKS:
        PARSE_HOOKS[ec.name](ec, eprefix)

    ec = inject_gpu_property(ec)


def pre_configure_hook(self, *args, **kwargs):
    """Main pre-configure hook: trigger custom functions based on software name."""

    if self.name in PRE_CONFIGURE_HOOKS:
        PRE_CONFIGURE_HOOKS[self.name](self, *args, **kwargs)


def pre_prepare_hook(self, *args, **kwargs):
    """Main pre-prepare hook: trigger custom functions."""

    # Check if we have an MPI family in the toolchain (returns None if there is not)
    mpi_family = self.toolchain.mpi_family()

    # Inject an RPATH override for MPI (if needed)
    if mpi_family:
        # Get list of override directories
        mpi_rpath_override_dirs = get_rpath_override_dirs(mpi_family)

        # update the relevant option (but keep the original value so we can reset it later)
        if hasattr(self, EESSI_RPATH_OVERRIDE_ATTR):
            raise EasyBuildError(
                "'self' already has attribute %s! Can't use pre_prepare hook.", EESSI_RPATH_OVERRIDE_ATTR
            )

        setattr(self, EESSI_RPATH_OVERRIDE_ATTR, build_option("rpath_override_dirs"))
        if getattr(self, EESSI_RPATH_OVERRIDE_ATTR):
            # self.EESSI_RPATH_OVERRIDE_ATTR is (already) a colon separated string, let's make it a list
            orig_rpath_override_dirs = [getattr(self, EESSI_RPATH_OVERRIDE_ATTR)]
            rpath_override_dirs = ":".join(orig_rpath_override_dirs + mpi_rpath_override_dirs)
        else:
            rpath_override_dirs = ":".join(mpi_rpath_override_dirs)
        update_build_option("rpath_override_dirs", rpath_override_dirs)
        print_msg(
            "Updated rpath_override_dirs (to allow overriding MPI family %s): %s", mpi_family, rpath_override_dirs
        )


def post_prepare_hook(self, *args, **kwargs):
    """Main post-prepare hook: trigger custom functions."""

    if hasattr(self, EESSI_RPATH_OVERRIDE_ATTR):
        # Reset the value of 'rpath_override_dirs' now that we are finished with it
        update_build_option("rpath_override_dirs", getattr(self, EESSI_RPATH_OVERRIDE_ATTR))
        print_msg("Resetting rpath_override_dirs to original value: %s", getattr(self, EESSI_RPATH_OVERRIDE_ATTR))
        delattr(self, EESSI_RPATH_OVERRIDE_ATTR)


def pre_configure_hook(self, *args, **kwargs):
    """Main pre-configure hook: trigger custom functions based on software name."""
    if self.name in PRE_CONFIGURE_HOOKS:
        PRE_CONFIGURE_HOOKS[self.name](self, *args, **kwargs)


def post_package_hook(self, *args, **kwargs):
    """Main post-package hook: trigger custom functions based on software name."""
    if self.name in POST_PACKAGE_HOOKS:
        POST_PACKAGE_HOOKS[self.name](self, *args, **kwargs)


# Functions used by hooks


def get_eessi_envvar(eessi_envvar):
    """Get an EESSI environment variable from the environment"""

    eessi_envvar_value = os.getenv(eessi_envvar)
    if eessi_envvar_value is None:
        raise EasyBuildError("$%s is not defined!", eessi_envvar)

    return eessi_envvar_value


def get_rpath_override_dirs(software_name):
    # determine path to installations in software layer via $EESSI_SOFTWARE_PATH
    eessi_software_path = get_eessi_envvar("EESSI_SOFTWARE_PATH")
    eessi_pilot_version = get_eessi_envvar("EESSI_PILOT_VERSION")

    # construct the rpath override directory stub
    rpath_injection_stub = os.path.join(
        # Make sure we are looking inside the `host_injections` directory
        eessi_software_path.replace(eessi_pilot_version, os.path.join("host_injections", eessi_pilot_version), 1),
        # Add the subdirectory for the specific software
        "rpath_overrides",
        software_name,
        # We can't know the version, but this allows the use of a symlink
        # to facilitate version upgrades without removing files
        "system",
    )

    # Allow for libraries in lib or lib64
    rpath_injection_dirs = [os.path.join(rpath_injection_stub, x) for x in ("lib", "lib64")]

    return rpath_injection_dirs


def cgal_toolchainopts_precise(ec, eprefix):
    """Enable 'precise' rather than 'strict' toolchain option for CGAL on POWER."""
    if ec.name == "CGAL":
        if get_cpu_architecture() == POWER:
            # 'strict' implies '-mieee-fp', which is not supported on POWER
            # see https://github.com/easybuilders/easybuild-framework/issues/2077
            ec["toolchainopts"]["strict"] = False
            ec["toolchainopts"]["precise"] = True
            print_msg("Tweaked toochainopts for %s: %s", ec.name, ec["toolchainopts"])
    else:
        raise EasyBuildError("CGAL-specific hook triggered for non-CGAL easyconfig?!")


def fontconfig_add_fonts(ec, eprefix):
    """Inject --with-add-fonts configure option for fontconfig."""
    if ec.name == "fontconfig":
        # make fontconfig aware of fonts included with compat layer
        with_add_fonts = "--with-add-fonts=%s" % os.path.join(eprefix, "usr", "share", "fonts")
        ec.update("configopts", with_add_fonts)
        print_msg("Added '%s' configure option for %s", with_add_fonts, ec.name)
    else:
        raise EasyBuildError("fontconfig-specific hook triggered for non-fontconfig easyconfig?!")


def ucx_eprefix(ec, eprefix):
    """Make UCX aware of compatibility layer via additional configuration options."""
    if ec.name == "UCX":
        ec.update("configopts", "--with-sysroot=%s" % eprefix)
        ec.update("configopts", "--with-rdmacm=%s" % os.path.join(eprefix, "usr"))
        print_msg("Using custom configure options for %s: %s", ec.name, ec["configopts"])
    else:
        raise EasyBuildError("UCX-specific hook triggered for non-UCX easyconfig?!")


def libfabric_disable_psm3_x86_64_generic(self, *args, **kwargs):
    """Add --disable-psm3 to libfabric configure options when building with --optarch=GENERIC on x86_64."""
    if self.name == "libfabric":
        if get_cpu_architecture() == X86_64:
            generic = build_option("optarch") == OPTARCH_GENERIC
            no_avx = "avx" not in get_cpu_features()
            if generic or no_avx:
                self.cfg.update("configopts", "--disable-psm3")
                print_msg("Using custom configure options for %s: %s", self.name, self.cfg["configopts"])
    else:
        raise EasyBuildError("libfabric-specific hook triggered for non-libfabric easyconfig?!")


def metabat_preconfigure(self, *args, **kwargs):
    """
    Pre-configure hook for MetaBAT:
    - take into account that zlib is a filtered dependency,
      and that there's no libz.a in the EESSI compat layer
    """
    if self.name == "MetaBAT":
        configopts = self.cfg["configopts"]
        regex = re.compile(r"\$EBROOTZLIB/lib/libz.a")
        self.cfg["configopts"] = regex.sub("$EPREFIX/usr/lib64/libz.so", configopts)
    else:
        raise EasyBuildError("MetaBAT-specific hook triggered for non-MetaBAT easyconfig?!")


def wrf_preconfigure(self, *args, **kwargs):
    """
    Pre-configure hook for WRF:
    - patch arch/configure_new.defaults so building WRF with foss toolchain works on aarch64
    """
    if self.name == "WRF":
        if get_cpu_architecture() == AARCH64:
            pattern = "Linux x86_64 ppc64le, gfortran"
            repl = "Linux x86_64 aarch64 ppc64le, gfortran"
            self.cfg.update("preconfigopts", "sed -i 's/%s/%s/g' arch/configure_new.defaults && " % (pattern, repl))
            print_msg("Using custom preconfigopts for %s: %s", self.name, self.cfg["preconfigopts"])
    else:
        raise EasyBuildError("WRF-specific hook triggered for non-WRF easyconfig?!")


def cuda_postpackage(self, *args, **kwargs):
    """Delete CUDA files we are not allowed to ship and replace them with a symlink to a possible installation under host_injections."""
    print_msg("Replacing CUDA stuff we cannot ship with symlinks...")
    # read CUDA EULA
    eula_path = os.path.join(self.installdir, "EULA.txt")
    tmp_buffer = []
    with open(eula_path) as infile:
        copy = False
        for line in infile:
            if line.strip() == "2.6. Attachment A":
                copy = True
                continue
            elif line.strip() == "2.7. Attachment B":
                copy = False
                continue
            elif copy:
                tmp_buffer.append(line)
    # create whitelist without file extensions, they're not really needed and they only complicate things
    whitelist = ['EULA']
    file_extensions = [".so", ".a", ".h", ".bc"]
    for tmp in tmp_buffer:
        for word in tmp.split():
            if any(ext in word for ext in file_extensions):
                whitelist.append(word.split(".")[0])
    whitelist = list(set(whitelist))
    # Do some quick checks for things we should or shouldn't have in the list
    if "nvcc" in whitelist:
        raise EasyBuildError("Found 'nvcc' in whitelist: %s" % whitelist)
    if "libcudart" not in whitelist:
        raise EasyBuildError("Did not find 'libcudart' in whitelist: %s" % whitelist)
    # iterate over all files in the CUDA path
    for root, dirs, files in os.walk(self.installdir):
        for filename in files:
            # we only really care about real files, i.e. not symlinks
            if not os.path.islink(os.path.join(root, filename)):
                # check if the current file is part of the whitelist
                basename = filename.split(".")[0]
                if basename not in whitelist:
                    # if it is not in the whitelist, delete the file and create a symlink to host_injections
                    source = os.path.join(root, filename)
                    target = source.replace("versions", "host_injections")
                    os.remove(source)
                    # Using os.symlink requires the existence of the target directory, so we use os.system
                    system_command="ln -s %s %s" % (target, source)
                    if os.system(system_command) != 0:
                        raise EasyBuildError("Failed to create symbolic link: %s" % system_command)


def inject_gpu_property(ec):
    ec_dict = ec.asdict()
    # Check if CUDA is in the dependencies, if so add the GPU Lmod tag
    if (
        "CUDA" in [dep[0] for dep in iter(ec_dict["dependencies"])]
        or ec_dict["toolchain"]["name"] in CUDA_ENABLED_TOOLCHAINS
    ):
        ec.log.info("[parse hook] Injecting gpu as Lmod arch property and envvar with CUDA version")
        key = "modluafooter"
        value = 'add_property("arch","gpu")'
        cuda_version = 0
        for dep in iter(ec_dict["dependencies"]):
            # Make CUDA a build dependency only (rpathing saves us from link errors)
            if "CUDA" in dep[0]:
                cuda_version = dep[1]
                ec_dict["dependencies"].remove(dep)
                ec_dict["builddependencies"].append(dep) if dep not in ec_dict["builddependencies"] else ec_dict[
                    "builddependencies"
                ]
        value = "\n".join([value, 'setenv("EESSICUDAVERSION","%s")' % cuda_version])
        if key in ec_dict:
            if not value in ec_dict[key]:
                ec[key] = "\n".join([ec_dict[key], value])
        else:
            ec[key] = value
    return ec

PARSE_HOOKS = {
    "CGAL": cgal_toolchainopts_precise,
    "fontconfig": fontconfig_add_fonts,
    "UCX": ucx_eprefix,
}

PRE_CONFIGURE_HOOKS = {
    "libfabric": libfabric_disable_psm3_x86_64_generic,
    "MetaBAT": metabat_preconfigure,
    "WRF": wrf_preconfigure,
}

POST_PACKAGE_HOOKS = {
    "CUDA": cuda_postpackage,
}
