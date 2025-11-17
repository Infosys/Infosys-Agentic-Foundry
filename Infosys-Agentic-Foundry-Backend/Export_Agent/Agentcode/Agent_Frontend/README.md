# Infosys Agentic Foundry

Infosys Agentic Foundry is a part of Infosys Topaz and provides a suite of components to help enterprises build reliable AI agents. It supports multiple agent design patterns and enables deployment through conversational interfaces or custom UIs, depending on your use case. Built with enterprise-grade reliability, Agentic Foundry ensures your business processes are robust and scalable.

## Getting Started

To get started with Infosys Agentic Foundry UI:

1. **Clone the repository from ExportAgent_UI branch**
   ```sh
   git clone https://github.com/Infosys-Generative-AI/Agentic-Pro-UI.git
   cd ExportAgent_UI
   ```

2. **Install dependencies:**
   ```sh
   npm install
   ```

3. **Start the development server:**
   ```sh
   npm start
   ```
   The app will be available at [http://localhost:3000](http://localhost:3000).

---

## Installation

- Ensure you have [Node.js](https://nodejs.org/) (v16 >= 23) and [npm](https://www.npmjs.com/) installed.
- Run `npm install` in the project root to install all dependencies.
- For production builds, use:
  ```sh
  npm run build
  ```
  The optimized build will be output to the `build/` directory.

---

## Configuration

- Configuration files (such as API endpoints, environment variables) can be managed using a `src/constant.js` file in the project root -> src.
- Example `constant.js`:
  ```
  export const BASE_URL = "https://<your-server-base-url-for-endpoints>
  ```
- Refer to the documentation or comments in `src/constant.js` for configurable constants.

---

## Available Scripts

In the project directory, you can run:

- `npm start` – Runs the app in development mode.
- `npm test` – Launches the test runner.
- `npm run build` – Builds the app for production.
- `npm run eject` – Ejects the app from Create React App (irreversible).

See [Create React App documentation](https://facebook.github.io/create-react-app/docs/getting-started) for more details.

---

## Project Structure

The project follows a standard React application structure:

```
Agentic-Pro-UI/
├── public/
│   └── index.html
├── src/
│   ├── components/
│   ├── constants.js
│   ├── App.js
│   ├── index.js
│   └── ...
├── package.json
└── README2.md
```
- `src/components/`: Contains reusable React components.
- `src/constants.js`: Stores configuration constants.
- `src/App.js`: Main application component.
- `public/`: Static assets and the HTML template.

---

## Features

- Modular and reusable React components.
- Support for multiple agent design patterns.
- Easy integration with APIs and backend services.
- Customizable UI for enterprise use cases.
- Built-in support for environment-based configuration.

---

## Customization

You can customize the UI and agent logic by modifying components in the `src/components/` directory and updating constants in `src/constants.js`. For environment-specific settings, use the `.env` file or update the configuration files as needed.

---

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch for your feature or bugfix.
3. Commit your changes with clear messages.
4. Push to your fork and submit a pull request.

Please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) file for detailed guidelines.

---

## License

This project is licensed under the [MIT License](LICENSE.md).  
Copyright © 2024-2025 Infosys Ltd.

---

## Support

For questions, issues, or feature requests, please open an issue in the [GitHub repository](https://github.com/Infosys-Generative-AI/Agentic-Pro-UI/issues) or contact the maintainers.

---

## Acknowledgements

- [Create React App](https://create-react-app.dev/) for the project scaffolding.
- [React](https://react.dev/) for the UI framework.
- [Infosys Topaz](https://www.infosys.com/services/ai-automation/topaz.html) for foundational AI agent concepts.
- All contributors and open-source libraries used in this project.

---

## Disclaimer

This software is provided "as is", without warranty of any kind. See the [LICENSE.md](LICENSE.md) file for more details.

© 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved. Infosys believes the information in this document is accurate as of its publication date; such information is subject to change without notice. Infosys acknowledges the proprietary rights of other companies to the trademarks, product names and such other intellectual property rights mentioned in this document. Except as expressly permitted, neither this documentation nor any part of it may be reproduced, stored in a retrieval system, or transmitted in any form or by any means, electronic, mechanical, printing, photocopying, recording or otherwise, without the prior permission of Infosys Limited and/or any named intellectual property rights holders under this document.
