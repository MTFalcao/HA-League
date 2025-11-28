document.addEventListener("DOMContentLoaded", () => {
    const flashes = document.querySelectorAll(".flash");
    flashes.forEach(flash => {
        setTimeout(() => {
            flash.classList.add("fade-out");
            setTimeout(() => flash.remove(), 600);
        }, 2000);
    });
});

