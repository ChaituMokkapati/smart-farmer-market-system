document.addEventListener("DOMContentLoaded", () => {
    const mobileToggles = document.querySelectorAll("[data-mobile-toggle]");
    const closeMobileMenu = (button, target, backdrop) => {
        target.classList.add("hidden");
        button.setAttribute("aria-expanded", "false");
        if (backdrop) {
            backdrop.classList.add("hidden");
        }
        document.body.classList.remove("mobile-menu-open");
    };

    mobileToggles.forEach((button) => {
        const target = document.getElementById(button.dataset.target);
        const backdrop = button.dataset.backdrop ? document.getElementById(button.dataset.backdrop) : null;
        if (!target) {
            return;
        }

        button.addEventListener("click", () => {
            const willOpen = target.classList.contains("hidden");
            target.classList.toggle("hidden", !willOpen);
            button.setAttribute("aria-expanded", willOpen ? "true" : "false");
            if (backdrop) {
                backdrop.classList.toggle("hidden", !willOpen);
            }
            document.body.classList.toggle("mobile-menu-open", willOpen);
        });

        if (backdrop) {
            backdrop.addEventListener("click", () => closeMobileMenu(button, target, backdrop));
        }

        target.querySelectorAll("a, button").forEach((item) => {
            item.addEventListener("click", () => {
                if (window.innerWidth < 1024 && !target.classList.contains("hidden")) {
                    closeMobileMenu(button, target, backdrop);
                }
            });
        });
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth >= 1024) {
            mobileToggles.forEach((button) => {
                const target = document.getElementById(button.dataset.target);
                const backdrop = button.dataset.backdrop ? document.getElementById(button.dataset.backdrop) : null;
                if (!target) {
                    return;
                }
                target.classList.remove("hidden");
                button.setAttribute("aria-expanded", "false");
                if (backdrop) {
                    backdrop.classList.add("hidden");
                }
            });
            document.body.classList.remove("mobile-menu-open");
        }
    });

    document.querySelectorAll("[data-dismiss-flash]").forEach((button) => {
        button.addEventListener("click", () => {
            const flash = button.closest("[data-flash]");
            if (!flash) {
                return;
            }

            flash.style.opacity = "0";
            flash.style.transform = "translateY(-10px)";
            setTimeout(() => flash.remove(), 200);
        });
    });

    document.querySelectorAll("[data-password-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById(button.dataset.passwordToggle);
            if (!input) {
                return;
            }

            const icon = button.querySelector("i");
            const isPassword = input.getAttribute("type") === "password";
            input.setAttribute("type", isPassword ? "text" : "password");

            if (icon) {
                icon.classList.toggle("fa-eye");
                icon.classList.toggle("fa-eye-slash");
            }
        });
    });

    const revealItems = document.querySelectorAll(".reveal, [data-reveal]");
    if ("IntersectionObserver" in window && revealItems.length) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-visible");
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12 });

        revealItems.forEach((item, index) => {
            item.style.transitionDelay = `${Math.min(index * 40, 240)}ms`;
            observer.observe(item);
        });
    } else {
        revealItems.forEach((item) => item.classList.add("is-visible"));
    }
});
