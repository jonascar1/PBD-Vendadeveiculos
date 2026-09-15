const passwordInput = document.getElementById("password");
const togglePassword = document.getElementById("togglePassword");

togglePassword.addEventListener("click", function () {

    if (passwordInput.type === "password") {

        passwordInput.type = "text";

        togglePassword.textContent = "Ocultar";

    } else {

        passwordInput.type = "password";

        togglePassword.textContent = "Mostrar";
    }
});